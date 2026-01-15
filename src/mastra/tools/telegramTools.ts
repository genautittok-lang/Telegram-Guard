import { createTool } from "@mastra/core/tools";
import { z } from "zod";

export const sendTelegramMessageTool = createTool({
  id: "send-telegram-message",
  description: "Надсилає повідомлення користувачу в Telegram",
  inputSchema: z.object({
    chatId: z.number().describe("ID чату Telegram"),
    text: z.string().describe("Текст повідомлення"),
    parseMode: z
      .enum(["HTML", "Markdown", "MarkdownV2"])
      .optional()
      .describe("Режим форматування"),
  }),
  outputSchema: z.object({
    success: z.boolean(),
    messageId: z.number().optional(),
    error: z.string().optional(),
  }),
  execute: async ({ context, mastra }) => {
    const logger = mastra?.getLogger();
    logger?.info("📤 [sendTelegramMessageTool] Надсилання повідомлення:", {
      chatId: context.chatId,
      textLength: context.text.length,
    });

    const botToken = process.env.TELEGRAM_BOT_TOKEN;
    if (!botToken) {
      logger?.error("❌ [sendTelegramMessageTool] TELEGRAM_BOT_TOKEN не налаштовано");
      return { success: false, error: "Bot token not configured" };
    }

    try {
      const response = await fetch(
        `https://api.telegram.org/bot${botToken}/sendMessage`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            chat_id: context.chatId,
            text: context.text,
            parse_mode: context.parseMode || "HTML",
          }),
        }
      );

      const data = await response.json();

      if (data.ok) {
        logger?.info("✅ [sendTelegramMessageTool] Повідомлення надіслано:", data.result.message_id);
        return { success: true, messageId: data.result.message_id };
      } else {
        logger?.error("❌ [sendTelegramMessageTool] Помилка API:", data);
        return { success: false, error: data.description };
      }
    } catch (error: any) {
      logger?.error("❌ [sendTelegramMessageTool] Помилка:", error);
      return { success: false, error: error.message };
    }
  },
});
