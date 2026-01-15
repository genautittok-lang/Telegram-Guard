import io
import qrcode
import os
import asyncio
import random
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError, PhoneNumberInvalidError
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.types import InputPhoneContact

load_dotenv()

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

user_states = {}
user_data = {}

db_pool = None

def init_pool():
    global db_pool
    db_pool = pool.SimpleConnectionPool(1, 10, DATABASE_URL)

def get_db():
    if db_pool:
        return db_pool.getconn()
    return psycopg2.connect(DATABASE_URL)

def release_db(conn):
    if db_pool:
        db_pool.putconn(conn)
    else:
        conn.close()

def init_db():
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'sessions'
        )
    """)
    table_exists = cur.fetchone()[0]
    
    if not table_exists:
        cur.execute('''
            CREATE TABLE sessions (
                id SERIAL PRIMARY KEY,
                owner_id BIGINT NOT NULL,
                phone VARCHAR(20) NOT NULL,
                api_id INTEGER NOT NULL,
                api_hash VARCHAR(100) NOT NULL,
                session_name VARCHAR(100) NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(owner_id, phone)
            )
        ''')
    else:
        cur.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'sessions' AND column_name = 'owner_id'
        """)
        if not cur.fetchone():
            cur.execute("ALTER TABLE sessions ADD COLUMN owner_id BIGINT DEFAULT 0")
            cur.execute("UPDATE sessions SET owner_id = 0 WHERE owner_id IS NULL")
            cur.execute("ALTER TABLE sessions ALTER COLUMN owner_id SET NOT NULL")
        
        cur.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'sessions' AND column_name = 'is_active'
        """)
        if not cur.fetchone():
            cur.execute("ALTER TABLE sessions ADD COLUMN is_active BOOLEAN DEFAULT TRUE")
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS pending_auth (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL UNIQUE,
            phone VARCHAR(20) NOT NULL,
            api_id INTEGER NOT NULL,
            api_hash VARCHAR(100) NOT NULL,
            session_name VARCHAR(100) NOT NULL,
            state VARCHAR(20) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cur.execute('CREATE INDEX IF NOT EXISTS idx_sessions_owner ON sessions(owner_id)')
    conn.commit()
    cur.close()
    release_db(conn)

def get_user_sessions(owner_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, phone, api_id, api_hash, session_name FROM sessions WHERE owner_id = %s AND is_active = TRUE",
        (owner_id,)
    )
    sessions = cur.fetchall()
    cur.close()
    release_db(conn)
    return sessions

def mark_session_inactive(session_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE sessions SET is_active = FALSE WHERE id = %s", (session_id,))
    conn.commit()
    cur.close()
    release_db(conn)

def save_pending_auth(user_id, phone, api_id, api_hash, session_name, state):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO pending_auth (user_id, phone, api_id, api_hash, session_name, state)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET 
        phone = EXCLUDED.phone,
        api_id = EXCLUDED.api_id,
        api_hash = EXCLUDED.api_hash,
        session_name = EXCLUDED.session_name,
        state = EXCLUDED.state,
        created_at = CURRENT_TIMESTAMP
    """, (user_id, phone, api_id, api_hash, session_name, state))
    conn.commit()
    cur.close()
    release_db(conn)

def get_pending_auth(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT phone, api_id, api_hash, session_name, state FROM pending_auth WHERE user_id = %s",
        (user_id,)
    )
    result = cur.fetchone()
    cur.close()
    release_db(conn)
    return result

def delete_pending_auth(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM pending_auth WHERE user_id = %s", (user_id,))
    conn.commit()
    cur.close()
    release_db(conn)

async def check_phone_in_telegram(api_id, api_hash, session_name, phone_to_check, session_id=None):
    client = TelegramClient(session_name, api_id, api_hash)
    await client.connect()
    
    if not await client.is_user_authorized():
        await client.disconnect()
        if session_id:
            mark_session_inactive(session_id)
        return {'error': 'Сесія не авторизована', 'session_invalid': True}
    
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
        return {'error': f'Ліміт! Зачекайте {e.seconds} сек', 'flood': True, 'wait_seconds': e.seconds}
    except Exception as e:
        await client.disconnect()
        return {'error': str(e)}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    pending = get_pending_auth(user_id)
    if pending:
        phone, api_id, api_hash, session_name, state = pending
        user_data[user_id] = {
            'phone': phone,
            'api_id': api_id,
            'api_hash': api_hash,
            'session_name': session_name
        }
        
        if state == 'waiting_code':
            client = TelegramClient(session_name, api_id, api_hash)
            await client.connect()
            try:
                await client.send_code_request(phone)
                user_data[user_id]['client'] = client
                user_states[user_id] = 'waiting_code'
                await update.message.reply_text(
                    f"📱 У тебе є незавершена авторизація для {phone}.\n"
                    "Код відправлено повторно. Введи код з SMS/Telegram:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🏠 Меню", callback_data='back')],
                        [InlineKeyboardButton("🔍 Використати QR-код", callback_data='auth_qr')]
                    ])
                )
                return
            except Exception as e:
                await client.disconnect()
                delete_pending_auth(user_id)
    
    keyboard = [
        [InlineKeyboardButton("📋 Перевірити список", callback_data='check_list')],
        [InlineKeyboardButton("➕ Додати сесію", callback_data='add_session')],
        [InlineKeyboardButton("📊 Мої сесії", callback_data='session_count')],
        [InlineKeyboardButton("🗑️ Видалити сесію", callback_data='delete_session')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 Привіт! Я бот для перевірки номерів в Telegram.\n\n"
        "📝 Надішли мені список номерів у форматі:\n"
        "+380991234567 Іван Петров\n"
        "+380997654321 Марія Сидоренко\n\n"
        "⚠️ Спочатку додай свою сесію (API_ID та API_HASH з my.telegram.org)\n\n"
        "Використовуй кнопки нижче:",
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"🔘 Кнопка натиснута: {update.callback_query.data}")
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        print(f"❌ Помилка answer: {e}")
    user_id = query.from_user.id
    print(f"👤 User ID: {user_id}, Data: {query.data}")
    
    if query.data == 'check_list':
        sessions = get_user_sessions(user_id)
        if not sessions:
            keyboard = [[InlineKeyboardButton("➕ Додати сесію", callback_data='add_session')]]
            await query.edit_message_text(
                "❌ У тебе немає активних сесій!\nСпочатку додай сесію.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
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
        delete_pending_auth(user_id)
        await query.edit_message_text(
            "📱 Надішли номер телефону для авторизації (формат: +380...)\n\n"
            "⚠️ Це твій особистий номер для перевірки інших номерів."
        )
    
    elif query.data == 'session_count':
        sessions = get_user_sessions(user_id)
        count = len(sessions)
        
        if count > 0:
            session_list = "\n".join([f"• {s[1]}" for s in sessions])
            text = f"📊 Твої активні сесії ({count}):\n\n{session_list}"
        else:
            text = "📊 У тебе немає активних сесій."
        
        keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='back')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == 'delete_session':
        sessions = get_user_sessions(user_id)
        
        if not sessions:
            keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='back')]]
            await query.edit_message_text(
                "❌ У тебе немає сесій для видалення.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        keyboard = [[InlineKeyboardButton(f"🗑️ {s[1]}", callback_data=f'del_{s[0]}')] for s in sessions]
        keyboard.append([InlineKeyboardButton("↩️ Назад", callback_data='back')])
        await query.edit_message_text(
            "Виберіть сесію для видалення:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data == 'auth_qr':
        data = user_data.get(user_id)
        if not data or 'api_id' not in data:
            await query.edit_message_text("❌ Спочатку введи номер та API дані.")
            return

        api_id = data['api_id']
        api_hash = data['api_hash']
        session_name = data.get('session_name', f'session_qr_{user_id}')
        
        client = TelegramClient(
            session_name, 
            api_id, 
            api_hash, 
            device_model="Samsung Galaxy S21", 
            system_version="Android 12",
            app_version="8.4.1"
        )
        await client.connect()
        
        try:
            qr_login = await client.qr_login()
            user_data[user_id]['client'] = client
            user_data[user_id]['qr_login'] = qr_login
            
            async def wait_for_qr():
                try:
                    await qr_login.wait()
                    # Success!
                    me = await client.get_me()
                    phone = me.phone
                    
                    conn = get_db()
                    cur = conn.cursor()
                    cur.execute(
                        """INSERT INTO sessions (owner_id, phone, api_id, api_hash, session_name) 
                           VALUES (%s, %s, %s, %s, %s) 
                           ON CONFLICT (owner_id, phone) DO UPDATE SET 
                           api_id = EXCLUDED.api_id, 
                           api_hash = EXCLUDED.api_hash, 
                           session_name = EXCLUDED.session_name,
                           is_active = TRUE""",
                        (user_id, phone, api_id, api_hash, session_name)
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                    
                    delete_pending_auth(user_id)
                    await client.disconnect()
                    if user_id in user_data:
                        del user_data[user_id]
                    user_states[user_id] = None
                    
                    await context.bot.send_message(user_id, "✅ Авторизація через QR-код успішна!")
                except SessionPasswordNeededError:
                    user_states[user_id] = 'waiting_2fa'
                    await context.bot.send_message(user_id, "🔐 У тебе ввімкнена двофакторна автентифікація (2FA). Будь ласка, введи свій пароль:")
                except Exception as e:
                    import traceback
                    print(f"❌ QR Auth Error: {e}")
                    traceback.print_exc()
                    await context.bot.send_message(user_id, f"❌ Помилка QR авторизації: {e}")

            asyncio.create_task(wait_for_qr())

            qr_url = qr_login.url
            img = qrcode.make(qr_url)
            bio = io.BytesIO()
            img.save(bio, 'PNG')
            bio.seek(0)
            
            await query.message.reply_photo(
                photo=bio,
                caption="🔍 Відскануй цей QR-код у налаштуваннях Telegram (Пристрої -> Підключити пристрій).\n\n"
                        "⚠️ Код дійсний 30 секунд. Після сканування бот автоматично додасть сесію."
            )
        except Exception as e:
            await query.edit_message_text(f"❌ Помилка створення QR: {e}")
            await client.disconnect()

    elif query.data == 'back':
        keyboard = [
            [InlineKeyboardButton("📋 Перевірити список", callback_data='check_list')],
            [InlineKeyboardButton("➕ Додати сесію", callback_data='add_session')],
            [InlineKeyboardButton("📊 Мої сесії", callback_data='session_count')],
            [InlineKeyboardButton("🗑️ Видалити сесію", callback_data='delete_session')],
        ]
        await query.edit_message_text(
            "👋 Головне меню:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data.startswith('del_'):
        session_id = int(query.data.replace('del_', ''))
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT session_name FROM sessions WHERE id = %s AND owner_id = %s", (session_id, user_id))
        row = cur.fetchone()
        if row:
            session_file = row[0] + '.session'
            if os.path.exists(session_file):
                os.remove(session_file)
            cur.execute("DELETE FROM sessions WHERE id = %s AND owner_id = %s", (session_id, user_id))
            conn.commit()
            text = "✅ Сесію видалено!"
        else:
            text = "❌ Сесію не знайдено."
        cur.close()
        conn.close()
        
        keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='back')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

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
    
    elif state == 'waiting_2fa':
        password = text
        client = user_data.get(user_id, {}).get('client')
        
        if not client:
            await update.message.reply_text("❌ Помилка: клієнт не знайдений. Спробуй почати спочатку.")
            user_states[user_id] = None
            return
            
        try:
            await client.sign_in(password=password)
            # Success!
            me = await client.get_me()
            phone = me.phone
            
            data = user_data.get(user_id, {})
            api_id = data.get('api_id')
            api_hash = data.get('api_hash')
            session_name = data.get('session_name', f'session_qr_{user_id}')
            
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO sessions (owner_id, phone, api_id, api_hash, session_name) 
                   VALUES (%s, %s, %s, %s, %s) 
                   ON CONFLICT (owner_id, phone) DO UPDATE SET 
                   api_id = EXCLUDED.api_id, 
                   api_hash = EXCLUDED.api_hash, 
                   session_name = EXCLUDED.session_name,
                   is_active = TRUE""",
                (user_id, phone, api_id, api_hash, session_name)
            )
            conn.commit()
            cur.close()
            conn.close()
            
            delete_pending_auth(user_id)
            if user_id in user_data:
                del user_data[user_id]
            user_states[user_id] = None
            
            await update.message.reply_text("✅ Авторизація успішна (2FA пройдено)!")
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка 2FA: {e}")
            print(f"❌ 2FA Error: {e}")
        user_data[user_id]['session_name'] = session_name
        
        save_pending_auth(user_id, phone, api_id, api_hash, session_name, 'waiting_code')
        
        client = TelegramClient(
            session_name, 
            api_id, 
            api_hash, 
            device_model="Samsung Galaxy S21", 
            system_version="Android 12",
            app_version="8.4.1"
        )
        await client.connect()
        
        try:
            print(f"📡 Відправка запиту коду для {phone} (API ID: {api_id})...", flush=True)
            # Force SMS if possible or just use default
            await client.send_code_request(phone)
            user_data[user_id]['client'] = client
            user_states[user_id] = 'waiting_code'
            
            keyboard = [
                [InlineKeyboardButton("🔍 Використати QR-код", callback_data='auth_qr')],
                [InlineKeyboardButton("🏠 Меню", callback_data='back')]
            ]
            await update.message.reply_text(
                "📱 Код надіслано! Введи код з SMS/Telegram (5 цифр).\n\n"
                "💡 Якщо код не приходить, спробуй авторизацію через QR-код:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except PhoneNumberInvalidError:
            print(f"❌ Невірний номер телефону: {phone}", flush=True)
            delete_pending_auth(user_id)
            await update.message.reply_text("❌ Невірний номер телефону. Перевір формат (+380...)")
            await client.disconnect()
        except Exception as e:
            print(f"❌ Помилка send_code_request: {e}", flush=True)
            delete_pending_auth(user_id)
            await update.message.reply_text(f"❌ Помилка: {str(e)}")
            await client.disconnect()
    
    elif state == 'waiting_code':
        data = user_data.get(user_id)
        
        if not data or 'client' not in data:
            pending = get_pending_auth(user_id)
            if pending:
                phone, api_id, api_hash, session_name, _ = pending
                client = TelegramClient(session_name, api_id, api_hash)
                await client.connect()
                user_data[user_id] = {
                    'phone': phone,
                    'api_id': api_id,
                    'api_hash': api_hash,
                    'session_name': session_name,
                    'client': client
                }
                data = user_data[user_id]
            else:
                keyboard = [[InlineKeyboardButton("➕ Додати сесію", callback_data='add_session')]]
                await update.message.reply_text(
                    "❌ Сесія не знайдена. Почни спочатку.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
        
        client = data['client']
        phone = data['phone']
        
        try:
            await client.sign_in(phone, text)
            
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO sessions (owner_id, phone, api_id, api_hash, session_name) 
                   VALUES (%s, %s, %s, %s, %s) 
                   ON CONFLICT (owner_id, phone) DO UPDATE SET 
                   api_id = EXCLUDED.api_id, 
                   api_hash = EXCLUDED.api_hash, 
                   session_name = EXCLUDED.session_name,
                   is_active = TRUE""",
                (user_id, phone, data['api_id'], data['api_hash'], data['session_name'])
            )
            conn.commit()
            cur.close()
            conn.close()
            
            delete_pending_auth(user_id)
            await client.disconnect()
            if user_id in user_data:
                del user_data[user_id]
            user_states[user_id] = None
            
            keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='back')]]
            await update.message.reply_text(
                "✅ Сесія успішно додана! Тепер можеш перевіряти номери.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except SessionPasswordNeededError:
            save_pending_auth(user_id, phone, data['api_id'], data['api_hash'], data['session_name'], 'waiting_2fa')
            user_states[user_id] = 'waiting_2fa'
            await update.message.reply_text("🔐 Потрібен 2FA пароль. Введи його:")
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {str(e)}")
    
    elif state == 'waiting_2fa':
        data = user_data.get(user_id)
        
        if not data or 'client' not in data:
            pending = get_pending_auth(user_id)
            if pending:
                phone, api_id, api_hash, session_name, _ = pending
                client = TelegramClient(session_name, api_id, api_hash)
                await client.connect()
                user_data[user_id] = {
                    'phone': phone,
                    'api_id': api_id,
                    'api_hash': api_hash,
                    'session_name': session_name,
                    'client': client
                }
                data = user_data[user_id]
            else:
                return
        
        client = data['client']
        phone = data['phone']
        
        try:
            await client.sign_in(password=text)
            
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO sessions (owner_id, phone, api_id, api_hash, session_name) 
                   VALUES (%s, %s, %s, %s, %s) 
                   ON CONFLICT (owner_id, phone) DO UPDATE SET 
                   api_id = EXCLUDED.api_id, 
                   api_hash = EXCLUDED.api_hash, 
                   session_name = EXCLUDED.session_name,
                   is_active = TRUE""",
                (user_id, phone, data['api_id'], data['api_hash'], data['session_name'])
            )
            conn.commit()
            cur.close()
            conn.close()
            
            delete_pending_auth(user_id)
            await client.disconnect()
            if user_id in user_data:
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
        sessions = get_user_sessions(user_id)
        
        if not sessions:
            keyboard = [[InlineKeyboardButton("➕ Додати сесію", callback_data='add_session')]]
            await update.message.reply_text(
                "❌ У тебе немає активних сесій! Додай сесію спочатку.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        await update.message.reply_text(f"⏳ Перевіряю номери... (сесій: {len(sessions)})")
        
        lines = text.strip().split('\n')
        results = []
        session_idx = 0
        failed_sessions = set()
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split(maxsplit=1)
            phone = parts[0] if parts else ''
            name = parts[1] if len(parts) > 1 else 'Невідомо'
            
            if not phone.startswith('+') and not phone.startswith('38') and not phone.startswith('7'):
                continue
            
            if not phone.startswith('+'):
                if phone.startswith('38'):
                    phone = '+' + phone
                elif phone.startswith('7'):
                    phone = '+' + phone
            
            check_result = None
            attempts = 0
            max_attempts = len(sessions)
            
            while attempts < max_attempts:
                current_idx = (session_idx + attempts) % len(sessions)
                if current_idx in failed_sessions:
                    attempts += 1
                    continue
                
                session = sessions[current_idx]
                session_id, _, api_id, api_hash, session_name = session
                
                check_result = await check_phone_in_telegram(api_id, api_hash, session_name, phone, session_id)
                
                if check_result.get('session_invalid'):
                    failed_sessions.add(current_idx)
                    attempts += 1
                    continue
                
                if check_result.get('flood'):
                    attempts += 1
                    continue
                
                break
            
            session_idx = (session_idx + 1) % len(sessions)
            
            if check_result is None:
                results.append(f"⚠️ {phone} {name} - Всі сесії недоступні")
            elif 'error' in check_result:
                results.append(f"⚠️ {phone} {name} - {check_result['error']}")
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

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Bot is running')
    def log_message(self, format, *args):
        pass

def start_health_server():
    server = HTTPServer(('0.0.0.0', 3000), HealthHandler)
    server.serve_forever()

def main():
    import sys
    import traceback
    
    try:
        print("🤖 Запуск бота...", flush=True)
        init_pool()
        init_db()
        
        health_thread = threading.Thread(target=start_health_server, daemon=True)
        health_thread.start()
        print("✅ Health server на порту 3000", flush=True)
        
        app = Application.builder().token(BOT_TOKEN).build()
        
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CallbackQueryHandler(button_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        print("✅ Бот запущено!", flush=True)
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    except Exception as e:
        print(f"❌ КРИТИЧНА ПОМИЛКА: {e}", flush=True)
        traceback.print_exc()
        raise

if __name__ == '__main__':
    main()
