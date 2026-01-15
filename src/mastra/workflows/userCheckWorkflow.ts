import { createStep, createWorkflow } from "../inngest";
import { z } from "zod";
import { userCheckAgent } from "../agents/userCheckAgent";
import { sendTelegramMessageTool } from "../tools/telegramTools";

const processWithAgent = createStep({
  id: "process-with-agent",
  description: "Обробляє повідомлення користувача через агента",
  inputSchema: z.object({
    message: z.string().describe("Повідомлення від користувача"),
    chatId: z.number().describe("ID чату Telegram"),
    userName: z.string().optional().describe("Ім'я користувача"),
  }),
  outputSchema: z.object({
    agentResponse: z.string(),
    chatId: z.number(),
  }),
  execute: async ({ inputData, mastra }) => {
    const logger = mastra?.getLogger();
    logger?.info("🚀 [Step 1] Обробка повідомлення агентом:", {
      message: inputData.message,
      chatId: inputData.chatId,
    });

    const response = await userCheckAgent.generateLegacy([
      { role: "user", content: inputData.message },
    ]);

    logger?.info("✅ [Step 1] Відповідь агента:", response.text);

    return {
      agentResponse: response.text,
      chatId: inputData.chatId,
    };
  },
});

const sendToTelegram = createStep({
  id: "send-to-telegram",
  description: "Надсилає відповідь агента в Telegram",
  inputSchema: z.object({
    agentResponse: z.string(),
    chatId: z.number(),
  }),
  outputSchema: z.object({
    success: z.boolean(),
    messageId: z.number().optional(),
  }),
  execute: async ({ inputData, mastra }) => {
    const logger = mastra?.getLogger();
    logger?.info("📤 [Step 2] Надсилання в Telegram:", {
      chatId: inputData.chatId,
      responseLength: inputData.agentResponse.length,
    });

    const result = await sendTelegramMessageTool.execute({
      context: {
        chatId: inputData.chatId,
        text: inputData.agentResponse,
        parseMode: "HTML",
      },
      mastra,
      runtimeContext: {} as any,
    });

    logger?.info("✅ [Step 2] Результат надсилання:", result);

    return {
      success: result.success,
      messageId: result.messageId,
    };
  },
});

export const userCheckWorkflow = createWorkflow({
  id: "user-check-workflow",
  inputSchema: z.object({
    message: z.string().describe("Повідомлення від користувача"),
    chatId: z.number().describe("ID чату Telegram"),
    userName: z.string().optional().describe("Ім'я користувача"),
  }) as any,
  outputSchema: z.object({
    success: z.boolean(),
    messageId: z.number().optional(),
  }),
})
  .then(processWithAgent as any)
  .then(sendToTelegram as any)
  .commit();
