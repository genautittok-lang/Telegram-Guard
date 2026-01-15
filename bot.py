import os
import asyncio
import random
import psycopg2
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.types import InputPhoneContact

load_dotenv()

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
API_ID = int(os.getenv('TELEGRAM_API_ID', '0'))
API_HASH = os.getenv('TELEGRAM_API_HASH', '')
DATABASE_URL = os.getenv('DATABASE_URL')

user_sessions = {}
user_states = {}

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            phone VARCHAR(20) NOT NULL UNIQUE,
            first_name VARCHAR(100) NOT NULL,
            last_name VARCHAR(100) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
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

bot = TelegramClient('bot_session', API_ID, API_HASH)

async def check_phone_in_telegram(session_client, phone):
    try:
        contact = InputPhoneContact(
            client_id=random.randint(0, 9999999),
            phone=phone,
            first_name="Check",
            last_name="User"
        )
        result = await session_client(ImportContactsRequest([contact]))
        
        if result.users:
            user = result.users[0]
            await session_client(DeleteContactsRequest(id=[user.id]))
            return {
                'registered': True,
                'first_name': user.first_name or '',
                'last_name': user.last_name or '',
                'username': user.username or ''
            }
        else:
            return {'registered': False}
    except FloodWaitError as e:
        return {'error': f'Зачекайте {e.seconds} секунд'}
    except Exception as e:
        return {'error': str(e)}

@bot.on(events.NewMessage(pattern='/start'))
async def start(event):
    keyboard = [
        [Button.inline("📋 Перевірити список", b'check_list')],
        [Button.inline("➕ Додати сесію", b'add_session')],
        [Button.inline("📊 Кількість сесій", b'session_count')],
        [Button.inline("🗑️ Видалити сесію", b'delete_session')],
    ]
    await event.reply(
        "👋 Привіт! Я бот для перевірки номерів в Telegram.\n\n"
        "📝 Надішли мені список номерів у форматі:\n"
        "+380991234567 Іван Петров\n"
        "+380997654321 Марія Сидоренко\n\n"
        "Або використовуй кнопки нижче:",
        buttons=keyboard
    )

@bot.on(events.CallbackQuery(data=b'check_list'))
async def check_list_callback(event):
    await event.answer()
    user_states[event.sender_id] = 'waiting_list'
    await event.respond(
        "📋 Надішли список номерів для перевірки.\n"
        "Формат: номер ім'я прізвище (кожен на новому рядку)\n\n"
        "Приклад:\n"
        "+380991234567 Іван Петров\n"
        "+380997654321 Марія Сидоренко"
    )

@bot.on(events.CallbackQuery(data=b'add_session'))
async def add_session_callback(event):
    await event.answer()
    user_states[event.sender_id] = 'waiting_phone'
    await event.respond(
        "📱 Надішли номер телефону для авторизації (формат: +380...)\n\n"
        "⚠️ Це потрібно для перевірки номерів в Telegram."
    )

@bot.on(events.CallbackQuery(data=b'session_count'))
async def session_count_callback(event):
    await event.answer()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM sessions")
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    await event.respond(f"📊 Кількість активних сесій: {count}")

@bot.on(events.CallbackQuery(data=b'delete_session'))
async def delete_session_callback(event):
    await event.answer()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT phone FROM sessions")
    sessions = cur.fetchall()
    cur.close()
    conn.close()
    
    if not sessions:
        await event.respond("❌ Немає активних сесій для видалення.")
        return
    
    buttons = [[Button.inline(f"🗑️ {s[0]}", f'del_{s[0]}'.encode())] for s in sessions]
    buttons.append([Button.inline("↩️ Назад", b'back')])
    await event.respond("Виберіть сесію для видалення:", buttons=buttons)

@bot.on(events.CallbackQuery(data=b'back'))
async def back_callback(event):
    await event.answer()
    await start(event)

@bot.on(events.CallbackQuery(pattern=b'del_'))
async def delete_specific_session(event):
    await event.answer()
    phone = event.data.decode().replace('del_', '')
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM sessions WHERE phone = %s", (phone,))
    conn.commit()
    cur.close()
    conn.close()
    
    session_file = f'session_{phone.replace("+", "")}.session'
    if os.path.exists(session_file):
        os.remove(session_file)
    
    await event.respond(f"✅ Сесію {phone} видалено!")

@bot.on(events.NewMessage)
async def handle_message(event):
    if event.text.startswith('/'):
        return
    
    sender_id = event.sender_id
    state = user_states.get(sender_id)
    
    if state == 'waiting_phone':
        phone = event.text.strip()
        if not phone.startswith('+'):
            await event.reply("❌ Номер має починатися з +")
            return
        
        user_sessions[sender_id] = {'phone': phone, 'step': 'waiting_api_id'}
        user_states[sender_id] = 'waiting_api_id'
        await event.reply("📝 Тепер надішли API ID (отримай на my.telegram.org)")
    
    elif state == 'waiting_api_id':
        try:
            api_id = int(event.text.strip())
            user_sessions[sender_id]['api_id'] = api_id
            user_states[sender_id] = 'waiting_api_hash'
            await event.reply("📝 Тепер надішли API HASH")
        except ValueError:
            await event.reply("❌ API ID має бути числом")
    
    elif state == 'waiting_api_hash':
        api_hash = event.text.strip()
        user_sessions[sender_id]['api_hash'] = api_hash
        
        phone = user_sessions[sender_id]['phone']
        api_id = user_sessions[sender_id]['api_id']
        
        session_name = f'session_{phone.replace("+", "")}'
        client = TelegramClient(session_name, api_id, api_hash)
        await client.connect()
        
        try:
            await client.send_code_request(phone)
            user_sessions[sender_id]['client'] = client
            user_sessions[sender_id]['session_name'] = session_name
            user_states[sender_id] = 'waiting_code'
            await event.reply("📱 Код надіслано! Введи код з SMS (5 цифр)")
        except Exception as e:
            await event.reply(f"❌ Помилка: {str(e)}")
            await client.disconnect()
    
    elif state == 'waiting_code':
        code = event.text.strip()
        session_data = user_sessions.get(sender_id)
        
        if not session_data or 'client' not in session_data:
            await event.reply("❌ Сесія не знайдена. Почни спочатку /start")
            return
        
        client = session_data['client']
        phone = session_data['phone']
        
        try:
            await client.sign_in(phone, code)
            
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO sessions (phone, api_id, api_hash, session_name) VALUES (%s, %s, %s, %s) ON CONFLICT (phone) DO UPDATE SET api_id = %s, api_hash = %s",
                (phone, session_data['api_id'], session_data['api_hash'], session_data['session_name'], session_data['api_id'], session_data['api_hash'])
            )
            conn.commit()
            cur.close()
            conn.close()
            
            await client.disconnect()
            del user_sessions[sender_id]
            user_states[sender_id] = None
            
            await event.reply("✅ Сесія успішно додана! Тепер можеш перевіряти номери.")
        except SessionPasswordNeededError:
            user_states[sender_id] = 'waiting_2fa'
            await event.reply("🔐 Потрібен 2FA пароль. Введи його:")
        except Exception as e:
            await event.reply(f"❌ Помилка: {str(e)}")
    
    elif state == 'waiting_2fa':
        password = event.text.strip()
        session_data = user_sessions.get(sender_id)
        client = session_data['client']
        phone = session_data['phone']
        
        try:
            await client.sign_in(password=password)
            
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO sessions (phone, api_id, api_hash, session_name) VALUES (%s, %s, %s, %s) ON CONFLICT (phone) DO UPDATE SET api_id = %s, api_hash = %s",
                (phone, session_data['api_id'], session_data['api_hash'], session_data['session_name'], session_data['api_id'], session_data['api_hash'])
            )
            conn.commit()
            cur.close()
            conn.close()
            
            await client.disconnect()
            del user_sessions[sender_id]
            user_states[sender_id] = None
            
            await event.reply("✅ 2FA пройдено! Сесія додана.")
        except Exception as e:
            await event.reply(f"❌ Помилка 2FA: {str(e)}")
    
    elif state == 'waiting_list' or (state is None and '\n' in event.text):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT phone, api_id, api_hash, session_name FROM sessions LIMIT 1")
        session = cur.fetchone()
        cur.close()
        conn.close()
        
        if not session:
            await event.reply("❌ Спочатку додай сесію для перевірки номерів!")
            return
        
        await event.reply("⏳ Перевіряю номери...")
        
        phone_db, api_id, api_hash, session_name = session
        client = TelegramClient(session_name, api_id, api_hash)
        await client.connect()
        
        if not await client.is_user_authorized():
            await event.reply("❌ Сесія не авторизована. Додай нову сесію.")
            await client.disconnect()
            return
        
        lines = event.text.strip().split('\n')
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
            
            check_result = await check_phone_in_telegram(client, phone)
            
            if 'error' in check_result:
                results.append(f"⚠️ {phone} {name} - Помилка: {check_result['error']}")
            elif check_result['registered']:
                tg_name = f"{check_result['first_name']} {check_result['last_name']}".strip()
                username = f"@{check_result['username']}" if check_result['username'] else ""
                results.append(f"✅ {phone} {name} - ЗАРЕЄСТРОВАНИЙ ({tg_name} {username})")
            else:
                results.append(f"❌ {phone} {name} - НЕ ЗАРЕЄСТРОВАНИЙ")
            
            await asyncio.sleep(random.uniform(2, 4))
        
        await client.disconnect()
        user_states[sender_id] = None
        
        if results:
            response = "📊 Результати перевірки:\n\n" + "\n".join(results)
            if len(response) > 4000:
                chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
                for chunk in chunks:
                    await event.reply(chunk)
            else:
                await event.reply(response)
        else:
            await event.reply("❌ Не знайдено жодного номера для перевірки")

async def main():
    print("🤖 Запуск бота...")
    init_db()
    await bot.start(bot_token=BOT_TOKEN)
    print("✅ Бот запущено!")
    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
