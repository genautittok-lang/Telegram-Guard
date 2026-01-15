import { createTool } from "@mastra/core/tools";
import { z } from "zod";
import pg from "pg";

const getPool = () => {
  return new pg.Pool({
    connectionString: process.env.DATABASE_URL,
  });
};

export const checkUserTool = createTool({
  id: "check-user",
  description: "Перевіряє чи існує користувач у базі за номером телефону",
  inputSchema: z.object({
    phone: z.string().describe("Номер телефону для перевірки"),
  }),
  outputSchema: z.object({
    found: z.boolean(),
    user: z
      .object({
        id: z.number(),
        phone: z.string(),
        firstName: z.string(),
        lastName: z.string(),
      })
      .nullable(),
  }),
  execute: async ({ context, mastra }) => {
    const logger = mastra?.getLogger();
    logger?.info("🔍 [checkUserTool] Перевірка номера:", context.phone);

    const pool = getPool();
    try {
      const normalizedPhone = context.phone.replace(/\D/g, "");
      const result = await pool.query(
        "SELECT id, phone, first_name, last_name FROM users WHERE REGEXP_REPLACE(phone, '[^0-9]', '', 'g') = $1",
        [normalizedPhone]
      );

      if (result.rows.length > 0) {
        const user = result.rows[0];
        logger?.info("✅ [checkUserTool] Користувач знайдений:", user);
        return {
          found: true,
          user: {
            id: user.id,
            phone: user.phone,
            firstName: user.first_name,
            lastName: user.last_name,
          },
        };
      }

      logger?.info("❌ [checkUserTool] Користувач не знайдений");
      return { found: false, user: null };
    } finally {
      await pool.end();
    }
  },
});

export const checkMultipleUsersTool = createTool({
  id: "check-multiple-users",
  description:
    "Перевіряє список користувачів за номерами телефонів. Приймає рядки у форматі: номер ім'я прізвище",
  inputSchema: z.object({
    userList: z.string().describe("Список користувачів, кожен на новому рядку"),
  }),
  outputSchema: z.object({
    results: z.array(
      z.object({
        phone: z.string(),
        inputName: z.string(),
        found: z.boolean(),
        dbUser: z
          .object({
            firstName: z.string(),
            lastName: z.string(),
          })
          .nullable(),
      })
    ),
    summary: z.object({
      total: z.number(),
      found: z.number(),
      notFound: z.number(),
    }),
  }),
  execute: async ({ context, mastra }) => {
    const logger = mastra?.getLogger();
    logger?.info("🔍 [checkMultipleUsersTool] Перевірка списку користувачів");

    const pool = getPool();
    const results: Array<{
      phone: string;
      inputName: string;
      found: boolean;
      dbUser: { firstName: string; lastName: string } | null;
    }> = [];

    try {
      const lines = context.userList.split("\n").filter((line) => line.trim());

      for (const line of lines) {
        const parts = line.trim().split(/\s+/);
        const phone = parts[0] || "";
        const inputName = parts.slice(1).join(" ") || "Невідомо";

        const normalizedPhone = phone.replace(/\D/g, "");
        const result = await pool.query(
          "SELECT first_name, last_name FROM users WHERE REGEXP_REPLACE(phone, '[^0-9]', '', 'g') = $1",
          [normalizedPhone]
        );

        if (result.rows.length > 0) {
          results.push({
            phone,
            inputName,
            found: true,
            dbUser: {
              firstName: result.rows[0].first_name,
              lastName: result.rows[0].last_name,
            },
          });
        } else {
          results.push({
            phone,
            inputName,
            found: false,
            dbUser: null,
          });
        }
      }

      const summary = {
        total: results.length,
        found: results.filter((r) => r.found).length,
        notFound: results.filter((r) => !r.found).length,
      };

      logger?.info("✅ [checkMultipleUsersTool] Результат:", summary);
      return { results, summary };
    } finally {
      await pool.end();
    }
  },
});

export const addUserTool = createTool({
  id: "add-user",
  description: "Додає нового користувача до бази даних",
  inputSchema: z.object({
    phone: z.string().describe("Номер телефону"),
    firstName: z.string().describe("Ім'я"),
    lastName: z.string().describe("Прізвище"),
  }),
  outputSchema: z.object({
    success: z.boolean(),
    message: z.string(),
    user: z
      .object({
        id: z.number(),
        phone: z.string(),
        firstName: z.string(),
        lastName: z.string(),
      })
      .nullable(),
  }),
  execute: async ({ context, mastra }) => {
    const logger = mastra?.getLogger();
    logger?.info("➕ [addUserTool] Додавання користувача:", context);

    const pool = getPool();
    try {
      const result = await pool.query(
        "INSERT INTO users (phone, first_name, last_name) VALUES ($1, $2, $3) RETURNING id, phone, first_name, last_name",
        [context.phone, context.firstName, context.lastName]
      );

      const user = result.rows[0];
      logger?.info("✅ [addUserTool] Користувач доданий:", user);
      return {
        success: true,
        message: "Користувача успішно додано",
        user: {
          id: user.id,
          phone: user.phone,
          firstName: user.first_name,
          lastName: user.last_name,
        },
      };
    } catch (error: any) {
      if (error.code === "23505") {
        logger?.warn("⚠️ [addUserTool] Користувач вже існує");
        return {
          success: false,
          message: "Користувач з таким номером вже існує",
          user: null,
        };
      }
      throw error;
    } finally {
      await pool.end();
    }
  },
});

export const addMultipleUsersTool = createTool({
  id: "add-multiple-users",
  description:
    "Додає кілька користувачів до бази. Формат: номер ім'я прізвище (кожен на новому рядку)",
  inputSchema: z.object({
    userList: z
      .string()
      .describe("Список користувачів для додавання, кожен на новому рядку"),
  }),
  outputSchema: z.object({
    added: z.number(),
    skipped: z.number(),
    errors: z.array(z.string()),
  }),
  execute: async ({ context, mastra }) => {
    const logger = mastra?.getLogger();
    logger?.info("➕ [addMultipleUsersTool] Додавання списку користувачів");

    const pool = getPool();
    let added = 0;
    let skipped = 0;
    const errors: string[] = [];

    try {
      const lines = context.userList.split("\n").filter((line) => line.trim());

      for (const line of lines) {
        const parts = line.trim().split(/\s+/);
        if (parts.length < 3) {
          errors.push(`Невірний формат: ${line}`);
          continue;
        }

        const phone = parts[0];
        const firstName = parts[1];
        const lastName = parts.slice(2).join(" ");

        try {
          await pool.query(
            "INSERT INTO users (phone, first_name, last_name) VALUES ($1, $2, $3)",
            [phone, firstName, lastName]
          );
          added++;
        } catch (error: any) {
          if (error.code === "23505") {
            skipped++;
          } else {
            errors.push(`Помилка для ${phone}: ${error.message}`);
          }
        }
      }

      logger?.info("✅ [addMultipleUsersTool] Результат:", {
        added,
        skipped,
        errors: errors.length,
      });
      return { added, skipped, errors };
    } finally {
      await pool.end();
    }
  },
});

export const deleteUserTool = createTool({
  id: "delete-user",
  description: "Видаляє користувача з бази за номером телефону",
  inputSchema: z.object({
    phone: z.string().describe("Номер телефону користувача для видалення"),
  }),
  outputSchema: z.object({
    success: z.boolean(),
    message: z.string(),
  }),
  execute: async ({ context, mastra }) => {
    const logger = mastra?.getLogger();
    logger?.info("🗑️ [deleteUserTool] Видалення користувача:", context.phone);

    const pool = getPool();
    try {
      const normalizedPhone = context.phone.replace(/\D/g, "");
      const result = await pool.query(
        "DELETE FROM users WHERE REGEXP_REPLACE(phone, '[^0-9]', '', 'g') = $1 RETURNING phone",
        [normalizedPhone]
      );

      if (result.rowCount && result.rowCount > 0) {
        logger?.info("✅ [deleteUserTool] Користувач видалений");
        return { success: true, message: "Користувача успішно видалено" };
      }

      logger?.warn("⚠️ [deleteUserTool] Користувач не знайдений");
      return { success: false, message: "Користувача з таким номером не знайдено" };
    } finally {
      await pool.end();
    }
  },
});

export const editUserTool = createTool({
  id: "edit-user",
  description: "Редагує дані користувача за номером телефону",
  inputSchema: z.object({
    phone: z.string().describe("Номер телефону користувача для редагування"),
    newFirstName: z.string().optional().describe("Нове ім'я"),
    newLastName: z.string().optional().describe("Нове прізвище"),
    newPhone: z.string().optional().describe("Новий номер телефону"),
  }),
  outputSchema: z.object({
    success: z.boolean(),
    message: z.string(),
  }),
  execute: async ({ context, mastra }) => {
    const logger = mastra?.getLogger();
    logger?.info("✏️ [editUserTool] Редагування користувача:", context);

    const pool = getPool();
    try {
      const normalizedPhone = context.phone.replace(/\D/g, "");

      const updates: string[] = [];
      const values: any[] = [];
      let paramIndex = 1;

      if (context.newFirstName) {
        updates.push(`first_name = $${paramIndex++}`);
        values.push(context.newFirstName);
      }
      if (context.newLastName) {
        updates.push(`last_name = $${paramIndex++}`);
        values.push(context.newLastName);
      }
      if (context.newPhone) {
        updates.push(`phone = $${paramIndex++}`);
        values.push(context.newPhone);
      }

      if (updates.length === 0) {
        return { success: false, message: "Немає даних для оновлення" };
      }

      values.push(normalizedPhone);
      const result = await pool.query(
        `UPDATE users SET ${updates.join(", ")} WHERE REGEXP_REPLACE(phone, '[^0-9]', '', 'g') = $${paramIndex} RETURNING id`,
        values
      );

      if (result.rowCount && result.rowCount > 0) {
        logger?.info("✅ [editUserTool] Користувач оновлений");
        return { success: true, message: "Дані користувача успішно оновлено" };
      }

      logger?.warn("⚠️ [editUserTool] Користувач не знайдений");
      return { success: false, message: "Користувача з таким номером не знайдено" };
    } finally {
      await pool.end();
    }
  },
});

export const getUserCountTool = createTool({
  id: "get-user-count",
  description: "Отримує загальну кількість користувачів у базі",
  inputSchema: z.object({}),
  outputSchema: z.object({
    count: z.number(),
  }),
  execute: async ({ mastra }) => {
    const logger = mastra?.getLogger();
    logger?.info("📊 [getUserCountTool] Підрахунок користувачів");

    const pool = getPool();
    try {
      const result = await pool.query("SELECT COUNT(*) as count FROM users");
      const count = parseInt(result.rows[0].count, 10);
      logger?.info("✅ [getUserCountTool] Кількість:", count);
      return { count };
    } finally {
      await pool.end();
    }
  },
});

export const listUsersTool = createTool({
  id: "list-users",
  description: "Отримує список всіх користувачів у базі",
  inputSchema: z.object({
    limit: z.number().optional().describe("Максимальна кількість записів"),
  }),
  outputSchema: z.object({
    users: z.array(
      z.object({
        id: z.number(),
        phone: z.string(),
        firstName: z.string(),
        lastName: z.string(),
      })
    ),
    total: z.number(),
  }),
  execute: async ({ context, mastra }) => {
    const logger = mastra?.getLogger();
    logger?.info("📋 [listUsersTool] Отримання списку користувачів");

    const pool = getPool();
    try {
      const limit = context.limit || 50;
      const result = await pool.query(
        "SELECT id, phone, first_name, last_name FROM users ORDER BY id DESC LIMIT $1",
        [limit]
      );

      const countResult = await pool.query("SELECT COUNT(*) as count FROM users");
      const total = parseInt(countResult.rows[0].count, 10);

      const users = result.rows.map((row) => ({
        id: row.id,
        phone: row.phone,
        firstName: row.first_name,
        lastName: row.last_name,
      }));

      logger?.info("✅ [listUsersTool] Знайдено:", users.length);
      return { users, total };
    } finally {
      await pool.end();
    }
  },
});
