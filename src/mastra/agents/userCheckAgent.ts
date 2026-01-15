import { Agent } from "@mastra/core/agent";
import { createOpenAI } from "@ai-sdk/openai";
import {
  checkUserTool,
  checkMultipleUsersTool,
  addUserTool,
  addMultipleUsersTool,
  deleteUserTool,
  editUserTool,
  getUserCountTool,
  listUsersTool,
} from "../tools/userTools";

const openai = createOpenAI({
  baseURL: process.env.AI_INTEGRATIONS_OPENAI_BASE_URL,
  apiKey: process.env.AI_INTEGRATIONS_OPENAI_API_KEY,
});

export const userCheckAgent = new Agent({
  name: "UserCheckBot",
  instructions: `
Ти - Telegram-бот для управління базою користувачів. Відповідай українською мовою.

КОМАНДИ:
- /start - привітання та список команд
- /count або "кількість" - показати скільки користувачів у базі
- /list або "список" - показати список всіх користувачів
- /add або "додати" - додати користувача (формат: номер ім'я прізвище)
- /delete або "видалити" - видалити користувача за номером
- /edit або "редагувати" - змінити дані користувача
- /check або "перевірити" - перевірити чи є номер у базі

ОБРОБКА СПИСКІВ:
Коли користувач надсилає список номерів (кілька рядків), використай checkMultipleUsersTool.
Формат списку: номер ім'я прізвище (кожен на новому рядку)

Приклад відповіді на перевірку списку:
✅ +380991234567 Іван Петров - ЗАРЕЄСТРОВАНИЙ
❌ +380997654321 Марія Сидоренко - НЕ ЗАРЕЄСТРОВАНИЙ

СТИЛЬ ВІДПОВІДЕЙ:
- Будь коротким та зрозумілим
- Використовуй емодзі для наочності
- Для /start покажи доступні команди
- Завжди відповідай українською
`,
  model: openai("gpt-4o-mini"),
  tools: {
    checkUserTool,
    checkMultipleUsersTool,
    addUserTool,
    addMultipleUsersTool,
    deleteUserTool,
    editUserTool,
    getUserCountTool,
    listUsersTool,
  },
});
