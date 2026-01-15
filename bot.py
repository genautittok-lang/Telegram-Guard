import os
import asyncio
import random
import psycopg2
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.types import InputPhoneContact

load_dotenv()

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

user_states = {}
user_data = {}

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id SERIAL PRIMARY KEY,
            phone VARCHAR(20) NOT NULL UNIQUE,
            api_id INTEGER NOT NULL,
            api_hash VARCHAR(100) NOT NULL,
            session_name VARCHAR(100) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

async def check_phone_in_telegram(api_id, api_hash, session_name, phone_to_check):
    client = TelegramClient(session_name, api_id, api_hash)
    await client.connect()
    
    if not await client.is_user_authorized():
        await client.disconnect()
        return {'error': 'Сесія не авторизована'}
    
    try:
        contact = InputPhoneContact(
            client_id=random.randint(0, 9999999),
            phone=phone_to_check,
            first_name="Check",
            last_name="User"
        )
        result = await client(ImportContactsRequest([contact]))
        
        if result.users:
            user = result.users[0]
            await client(DeleteContactsRequest(id=[user.id]))
            await client.disconnect()
            return {
                'registered': True,
                'first_name': user.first_name or '',
                'last_name': user.last_name or '',
                'username': user.username or ''
            }
        else:
            await client.disconnect()
            return {'registered': False}
    except FloodWaitError as e:
        await client.disconnect()
        return {'error': f'Зачекайте {e.seconds} секунд'}
    except Exception as e:
        await client.disconnect()
        return {'error': str(e)}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📋 Перевірити список", callback_data='check_list')],
        [InlineKeyboardButton("➕ Додати сесію", callback_data='add_session')],
        [InlineKeyboardButton("📊 Кількість сесій", callback_data='session_count')],
        [InlineKeyboardButton("🗑️ Видалити сесію", callback_data='delete_session')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 Привіт! Я бот для перевірки номерів в Telegram.\n\n"
        "📝 Надішли мені список номерів у форматі:\n"
        "+380991234567 Іван Петров\n"
        "+380997654321 Марія Сидоренко\n\n"
        "Або використовуй кнопки нижче:",
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == 'check_list':
        user_states[user_id] = 'waiting_list'
        await query.edit_message_text(
            "📋 Надішли список номерів для перевірки.\n"
            "Формат: номер ім'я прізвище (кожен на новому рядку)\n\n"
            "Приклад:\n"
            "+380991234567 Іван Петров\n"
            "+380997654321 Марія Сидоренко"
        )
    
    elif query.data == 'add_session':
        user_states[user_id] = 'waiting_phone'
        user_data[user_id] = {}
        await query.edit_message_text(
            "📱 Надішли номер телефону для авторизації (формат: +380...)\n\n"
            "⚠️ Це потрібно для перевірки номерів в Telegram."
        )
    
    elif query.data == 'session_count':
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sessions")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        
        keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='back')]]
        await query.edit_message_text(
            f"📊 Кількість активних сесій: {count}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data == 'delete_session':
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT phone FROM sessions")
        sessions = cur.fetchall()
        cur.close()
        conn.close()
        
        if not sessions:
            keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='back')]]
            await query.edit_message_text(
                "❌ Немає активних сесій для видалення.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        keyboard = [[InlineKeyboardButton(f"🗑️ {s[0]}", callback_data=f'del_{s[0]}')] for s in sessions]
        keyboard.append([InlineKeyboardButton("↩️ Назад", callback_data='back')])
        await query.edit_message_text(
            "Виберіть сесію для видалення:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data == 'back':
        keyboard = [
            [InlineKeyboardButton("📋 Перевірити список", callback_data='check_list')],
            [InlineKeyboardButton("➕ Додати сесію", callback_data='add_session')],
            [InlineKeyboardButton("📊 Кількість сесій", callback_data='session_count')],
            [InlineKeyboardButton("🗑️ Видалити сесію", callback_data='delete_session')],
        ]
        await query.edit_message_text(
            "👋 Головне меню:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data.startswith('del_'):
        phone = query.data.replace('del_', '')
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT session_name FROM sessions WHERE phone = %s", (phone,))
        row = cur.fetchone()
        if row:
            session_file = row[0] + '.session'
            if os.path.exists(session_file):
                os.remove(session_file)
        cur.execute("DELETE FROM sessions WHERE phone = %s", (phone,))
        conn.commit()
        cur.close()
        conn.close()
        
        keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='back')]]
        await query.edit_message_text(
            f"✅ Сесію {phone} видалено!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    state = user_states.get(user_id)
    
    if state == 'waiting_phone':
        if not text.startswith('+'):
            await update.message.reply_text("❌ Номер має починатися з +")
            return
        
        user_data[user_id] = {'phone': text}
        user_states[user_id] = 'waiting_api_id'
        await update.message.reply_text("📝 Тепер надішли API ID (отримай на my.telegram.org)")
    
    elif state == 'waiting_api_id':
        try:
            api_id = int(text)
            user_data[user_id]['api_id'] = api_id
            user_states[user_id] = 'waiting_api_hash'
            await update.message.reply_text("📝 Тепер надішли API HASH")
        except ValueError:
            await update.message.reply_text("❌ API ID має бути числом")
    
    elif state == 'waiting_api_hash':
        user_data[user_id]['api_hash'] = text
        phone = user_data[user_id]['phone']
        api_id = user_data[user_id]['api_id']
        api_hash = text
        
        session_name = f'session_{phone.replace("+", "").replace(" ", "")}'
        user_data[user_id]['session_name'] = session_name
        
        client = TelegramClient(session_name, api_id, api_hash)
        await client.connect()
        
        try:
            await client.send_code_request(phone)
            user_data[user_id]['client'] = client
            user_states[user_id] = 'waiting_code'
            await update.message.reply_text("📱 Код надіслано! Введи код з SMS (5 цифр)")
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {str(e)}")
            await client.disconnect()
    
    elif state == 'waiting_code':
        data = user_data.get(user_id)
        if not data or 'client' not in data:
            await update.message.reply_text("❌ Сесія не знайдена. Почни спочатку /start")
            return
        
        client = data['client']
        phone = data['phone']
        
        try:
            await client.sign_in(phone, text)
            
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO sessions (phone, api_id, api_hash, session_name) 
                   VALUES (%s, %s, %s, %s) 
                   ON CONFLICT (phone) DO UPDATE SET api_id = %s, api_hash = %s, session_name = %s""",
                (phone, data['api_id'], data['api_hash'], data['session_name'],
                 data['api_id'], data['api_hash'], data['session_name'])
            )
            conn.commit()
            cur.close()
            conn.close()
            
            await client.disconnect()
            del user_data[user_id]
            user_states[user_id] = None
            
            keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='back')]]
            await update.message.reply_text(
                "✅ Сесія успішно додана! Тепер можеш перевіряти номери.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except SessionPasswordNeededError:
            user_states[user_id] = 'waiting_2fa'
            await update.message.reply_text("🔐 Потрібен 2FA пароль. Введи його:")
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {str(e)}")
    
    elif state == 'waiting_2fa':
        data = user_data.get(user_id)
        client = data['client']
        phone = data['phone']
        
        try:
            await client.sign_in(password=text)
            
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO sessions (phone, api_id, api_hash, session_name) 
                   VALUES (%s, %s, %s, %s) 
                   ON CONFLICT (phone) DO UPDATE SET api_id = %s, api_hash = %s, session_name = %s""",
                (phone, data['api_id'], data['api_hash'], data['session_name'],
                 data['api_id'], data['api_hash'], data['session_name'])
            )
            conn.commit()
            cur.close()
            conn.close()
            
            await client.disconnect()
            del user_data[user_id]
            user_states[user_id] = None
            
            keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='back')]]
            await update.message.reply_text(
                "✅ 2FA пройдено! Сесія додана.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка 2FA: {str(e)}")
    
    elif state == 'waiting_list' or '\n' in text or text.startswith('+'):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT phone, api_id, api_hash, session_name FROM sessions LIMIT 1")
        session = cur.fetchone()
        cur.close()
        conn.close()
        
        if not session:
            keyboard = [[InlineKeyboardButton("➕ Додати сесію", callback_data='add_session')]]
            await update.message.reply_text(
                "❌ Спочатку додай сесію для перевірки номерів!",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        await update.message.reply_text("⏳ Перевіряю номери...")
        
        phone_db, api_id, api_hash, session_name = session
        
        lines = text.strip().split('\n')
        results = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split(maxsplit=1)
            phone = parts[0] if parts else ''
            name = parts[1] if len(parts) > 1 else 'Невідомо'
            
            if not phone.startswith('+') and not phone.startswith('38'):
                continue
            
            if not phone.startswith('+'):
                phone = '+' + phone
            
            check_result = await check_phone_in_telegram(api_id, api_hash, session_name, phone)
            
            if 'error' in check_result:
                results.append(f"⚠️ {phone} {name} - Помилка: {check_result['error']}")
            elif check_result['registered']:
                tg_name = f"{check_result['first_name']} {check_result['last_name']}".strip()
                username = f"@{check_result['username']}" if check_result['username'] else ""
                results.append(f"✅ {phone} {name} - ЗАРЕЄСТРОВАНИЙ ({tg_name} {username})")
            else:
                results.append(f"❌ {phone} {name} - НЕ ЗАРЕЄСТРОВАНИЙ")
            
            await asyncio.sleep(random.uniform(2, 4))
        
        user_states[user_id] = None
        
        if results:
            response = "📊 Результати перевірки:\n\n" + "\n".join(results)
            if len(response) > 4000:
                chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
                for chunk in chunks:
                    await update.message.reply_text(chunk)
            else:
                keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='back')]]
                await update.message.reply_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text("❌ Не знайдено жодного номера для перевірки")

def main():
    print("🤖 Запуск бота...")
    init_db()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Бот запущено!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
