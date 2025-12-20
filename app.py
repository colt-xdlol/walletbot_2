import os
import json
import random
import string
import time
import sqlite3
import threading
import hashlib
import hmac
import urllib.parse
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from telebot import TeleBot

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.urandom(24).hex()

# Флаг тестового режима (для локального запуска без реального Telegram Web App)
TEST_MODE = os.environ.get('TEST_MODE', 'true').lower() in ('1', 'true', 'yes')

BOT_TOKEN = os.environ.get('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')

if BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
    BOT_TOKEN = '5001151811:AAFbZV5DKE4-8WiQXk3YEsmWQTq8CwGDoPk/test'
    print("⚠️ Используется токен из кода. Для продакшена используйте переменную окружения BOT_TOKEN")

if ':' not in BOT_TOKEN:
    raise ValueError('Токен бота должен содержать двоеточие. Формат: номер:токен')

bot = TeleBot(BOT_TOKEN)

ADMIN_TG_ID = 5000479220

def init_db():
    conn = sqlite3.connect('wallet.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id INTEGER,
        username TEXT UNIQUE,
        first_name TEXT,
        password_hash TEXT,
        wallet_address TEXT UNIQUE,
        balance REAL DEFAULT 0.0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        banned INTEGER DEFAULT 0
    )''')
    
    c.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in c.fetchall()]
    
    if 'password_hash' not in columns:
        try:
            c.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        except Exception as e:
            print(f"Ошибка добавления колонки password_hash: {e}")
    
    if 'wallet_address' not in columns:
        try:
            c.execute("ALTER TABLE users ADD COLUMN wallet_address TEXT UNIQUE")
        except Exception as e:
            print(f"Ошибка добавления колонки wallet_address: {e}")
    
    if 'start_count' not in columns:
        try:
            c.execute("ALTER TABLE users ADD COLUMN start_count INTEGER DEFAULT 0")
        except Exception as e:
            print(f"Ошибка добавления колонки start_count: {e}")
    
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        transaction_type TEXT NOT NULL,
        amount REAL NOT NULL,
        description TEXT,
        status TEXT DEFAULT 'completed',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS login_codes (
        code TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        min_deposit REAL DEFAULT 10.0,
        max_deposit REAL DEFAULT 100000.0,
        min_withdraw REAL DEFAULT 50.0,
        max_withdraw REAL DEFAULT 50000.0
    )''')
    
    c.execute("INSERT OR IGNORE INTO settings (min_deposit, max_deposit, min_withdraw, max_withdraw) VALUES (10.0, 100000.0, 50.0, 50000.0)")
    
    c.execute('''CREATE TABLE IF NOT EXISTS deposit_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )''')
    
    conn.commit()
    conn.close()
    print("База данных инициализирована")

init_db()

def generate_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def generate_wallet_address():
    return 'W' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=15))

def get_or_create_wallet_address(user_id):
    conn = sqlite3.connect('wallet.db')
    c = conn.cursor()
    try:
        c.execute("SELECT wallet_address FROM users WHERE id = ?", (user_id,))
        result = c.fetchone()
        
        if result and result[0]:
            return result[0]
        
        while True:
            address = generate_wallet_address()
            try:
                c.execute("UPDATE users SET wallet_address = ? WHERE id = ?", (address, user_id))
                conn.commit()
                return address
            except sqlite3.IntegrityError:
                continue
    finally:
        conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_user_avatar(tg_id):
    try:
        photos = bot.get_user_profile_photos(tg_id, limit=1)
        if photos.total_count > 0:
            file_id = photos.photos[0][0].file_id
            file_info = bot.get_file(file_id)
            return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
    except Exception as e:
        print(f"Ошибка получения аватарки: {e}")
    return None

def add_transaction(user_id, transaction_type, amount, description="", status="completed"):
    conn = sqlite3.connect('wallet.db')
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO transactions (user_id, transaction_type, amount, description, status)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, transaction_type, amount, description, status))
        conn.commit()
    except Exception as e:
        print(f"Ошибка добавления транзакции: {e}")
    finally:
        conn.close()

WEB_APP_URL = os.environ.get('WEB_APP_URL', 'http://46.202.82.69:1218')

@bot.message_handler(commands=['start'])
def start_bot(message):
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
    
    conn = sqlite3.connect('wallet.db')
    c = conn.cursor()
    
    try:
        tg_id = message.chat.id
        username = message.from_user.username or ''
        first_name = message.from_user.first_name or "Пользователь"
        
        c.execute("SELECT id, banned, balance, wallet_address FROM users WHERE tg_id = ?", (tg_id,))
        user = c.fetchone()
        
        if not user:
            wallet_address = generate_wallet_address()
            balance = 0.0
            c.execute("""
                INSERT INTO users (tg_id, username, first_name, balance, wallet_address)
                VALUES (?, ?, ?, 0.0, ?)
            """, (tg_id, username.lower(), first_name, wallet_address))
            conn.commit()
            print(f"Создан новый пользователь: {first_name} (tg_id: {tg_id})")
        else:
            user_id, banned, balance, wallet_address = user
            if banned == 1:
                bot.send_message(tg_id, "❌ Вы забанены. Обратитесь к администратору.")
                return
            c.execute("UPDATE users SET username = ?, first_name = ? WHERE id = ?", 
                     (username.lower(), first_name, user_id))
            conn.commit()
        
        # Кнопка для открытия Web App
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(
            "💰 Открыть кошелек",
            web_app=WebAppInfo(url=WEB_APP_URL)
        ))
        
        bot.send_message(
            tg_id,
            f"👋 <b>Добро пожаловать в кошелек!</b>\n\n"
            f"💰 Баланс: <b>{balance:.2f} USDT</b>\n\n"
            f"Нажмите кнопку ниже, чтобы открыть кошелек:",
            parse_mode='HTML',
            reply_markup=markup
        )
    except Exception as e:
        print(f"Ошибка в start_bot: {e}")
        bot.reply_to(message, "Произошла ошибка, попробуйте снова")
    finally:
        conn.close()

@bot.message_handler(commands=['balance'])
def balance_bot(message):
    conn = sqlite3.connect('wallet.db')
    c = conn.cursor()
    
    try:
        tg_id = message.chat.id
        username = message.from_user.username
        
        if not username:
            bot.send_message(tg_id, "❌ У вас не установлен username в Telegram.")
            return
        
        c.execute("SELECT balance, banned FROM users WHERE username = ?", (username.lower(),))
        result = c.fetchone()
        
        if not result:
            bot.send_message(tg_id, "Вы не зарегистрированы. Используйте /start")
            return
        
        balance, banned = result
        
        if banned == 1:
            bot.send_message(tg_id, "❌ Вы забанены.")
            return
        
        bot.send_message(
            tg_id,
            f"💰 <b>Ваш баланс:</b> <code>{balance:.2f} ₽</code>",
            parse_mode='HTML'
        )
    except Exception as e:
        print(f"Ошибка в balance_bot: {e}")
    finally:
        conn.close()

@bot.message_handler(func=lambda m: m.text and m.text.startswith('/confirm_'))
def confirm_deposit(message):
    if message.chat.id != ADMIN_TG_ID:
        bot.send_message(message.chat.id, "❌ У вас нет прав для этой команды.")
        return
    
    try:
        request_id = int(message.text.split('_')[1])
    except:
        bot.send_message(message.chat.id, "❌ Неверный формат команды.")
        return
    
    conn = sqlite3.connect('wallet.db')
    c = conn.cursor()
    
    try:
        c.execute("SELECT user_id, amount, status FROM deposit_requests WHERE id = ?", (request_id,))
        request_data = c.fetchone()
        
        if not request_data:
            bot.send_message(message.chat.id, "❌ Заявка не найдена.")
            return
        
        user_id, amount, status = request_data
        
        if status != 'pending':
            bot.send_message(message.chat.id, f"❌ Заявка уже обработана (статус: {status}).")
            return
        
        c.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user_id))
        c.execute("UPDATE deposit_requests SET status = 'confirmed' WHERE id = ?", (request_id,))
        add_transaction(user_id, 'deposit', amount, f'Пополнение баланса на {amount:.2f} ₽')
        conn.commit()
        
        c.execute("SELECT tg_id, balance FROM users WHERE id = ?", (user_id,))
        user_data = c.fetchone()
        
        if user_data and user_data[0]:
            try:
                bot.send_message(
                    user_data[0],
                    f"✅ <b>Пополнение подтверждено!</b>\n\n"
                    f"💰 Сумма: <b>{amount:.2f} ₽</b>\n"
                    f"💳 Новый баланс: <b>{user_data[1]:.2f} ₽</b>",
                    parse_mode='HTML'
                )
            except Exception as e:
                print(f"Ошибка отправки уведомления пользователю: {e}")
        
        bot.send_message(message.chat.id, f"✅ Заявка #{request_id} подтверждена! Баланс пользователя пополнен на {amount:.2f} ₽")
    except Exception as e:
        print(f"Ошибка в confirm_deposit: {e}")
        bot.send_message(message.chat.id, "❌ Произошла ошибка.")
    finally:
        conn.close()

@bot.message_handler(func=lambda m: m.text and m.text.startswith('/reject_'))
def reject_deposit(message):
    if message.chat.id != ADMIN_TG_ID:
        bot.send_message(message.chat.id, "❌ У вас нет прав для этой команды.")
        return
    
    try:
        request_id = int(message.text.split('_')[1])
    except:
        bot.send_message(message.chat.id, "❌ Неверный формат команды.")
        return
    
    conn = sqlite3.connect('wallet.db')
    c = conn.cursor()
    
    try:
        c.execute("SELECT user_id, amount, status FROM deposit_requests WHERE id = ?", (request_id,))
        request_data = c.fetchone()
        
        if not request_data:
            bot.send_message(message.chat.id, "❌ Заявка не найдена.")
            return
        
        user_id, amount, status = request_data
        
        if status != 'pending':
            bot.send_message(message.chat.id, f"❌ Заявка уже обработана (статус: {status}).")
            return
        
        c.execute("UPDATE deposit_requests SET status = 'rejected' WHERE id = ?", (request_id,))
        conn.commit()
        
        c.execute("SELECT tg_id FROM users WHERE id = ?", (user_id,))
        user_data = c.fetchone()
        
        if user_data and user_data[0]:
            try:
                bot.send_message(
                    user_data[0],
                    f"❌ <b>Заявка на пополнение отклонена</b>\n\n"
                    f"💰 Сумма: <b>{amount:.2f} ₽</b>\n\n"
                    f"Обратитесь к администратору для уточнения причины.",
                    parse_mode='HTML'
                )
            except Exception as e:
                print(f"Ошибка отправки уведомления пользователю: {e}")
        
        bot.send_message(message.chat.id, f"❌ Заявка #{request_id} отклонена.")
    except Exception as e:
        print(f"Ошибка в reject_deposit: {e}")
        bot.send_message(message.chat.id, "❌ Произошла ошибка.")
    finally:
        conn.close()

@bot.message_handler(commands=['history'])
def history_bot(message):
    conn = sqlite3.connect('wallet.db')
    c = conn.cursor()
    
    try:
        tg_id = message.chat.id
        username = message.from_user.username
        
        if not username:
            bot.send_message(tg_id, "❌ У вас не установлен username в Telegram.")
            return
        
        c.execute("SELECT id FROM users WHERE username = ?", (username.lower(),))
        user = c.fetchone()
        
        if not user:
            bot.send_message(tg_id, "Вы не зарегистрированы. Используйте /start")
            return
        
        user_id = user[0]
        c.execute("""
            SELECT transaction_type, amount, description, created_at
            FROM transactions
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 10
        """, (user_id,))
        
        transactions = c.fetchall()
        
        if not transactions:
            bot.send_message(tg_id, "📝 История транзакций пуста")
            return
        
        msg = "📝 <b>Последние транзакции:</b>\n\n"
        for trans in transactions:
            trans_type, amount, desc, created_at = trans
            icon = "➕" if trans_type == "deposit" else "➖" if trans_type == "withdraw" else "💸"
            msg += f"{icon} <b>{trans_type.upper()}</b>: {amount:.2f} ₽\n"
            if desc:
                msg += f"   {desc}\n"
            msg += f"   <i>{created_at}</i>\n\n"
        
        bot.send_message(tg_id, msg, parse_mode='HTML')
    except Exception as e:
        print(f"Ошибка в history_bot: {e}")
    finally:
        conn.close()

def validate_telegram_data(init_data):
    """Проверка данных от Telegram Web App"""
    try:
        parsed = urllib.parse.parse_qs(init_data)
        hash_value = parsed.get('hash', [None])[0]
        if not hash_value:
            return None
        
        data_check_arr = []
        for key, value in parsed.items():
            if key != 'hash':
                data_check_arr.append(f"{key}={value[0]}")
        data_check_arr.sort()
        data_check_string = '\n'.join(data_check_arr)
        
        secret_key = hmac.new(b'WebAppData', BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        if calculated_hash == hash_value:
            user_data = parsed.get('user', [None])[0]
            if user_data:
                return json.loads(user_data)
        return None
    except Exception as e:
        print(f"Ошибка валидации Telegram данных: {e}")
        return None

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/auth', methods=['POST'])
def auth():
    """Авторизация через Telegram Web App.
    
    Автоматически определяет ID и username пользователя из Telegram.
    """
    data = request.get_json() or {}
    init_data = data.get('initData', '')
    
    # Получаем данные пользователя, переданные напрямую из Telegram WebApp
    tg_id = data.get('tg_id')
    # Преобразуем tg_id в int, если он передан как строка
    if tg_id:
        try:
            tg_id = int(tg_id)
        except (ValueError, TypeError):
            tg_id = None
    
    username = (data.get('username') or '').lower().strip()
    first_name = data.get('first_name', '').strip() or 'Пользователь'
    
    print(f"[AUTH] Получены данные: tg_id={tg_id}, username={username}, first_name={first_name}")
    
    # Пробуем валидировать initData (для дополнительной безопасности)
    if init_data:
        user_data = validate_telegram_data(init_data)
        if user_data:
            # Если валидация успешна, используем данные из неё (они более надежные)
            tg_id = user_data.get('id') or tg_id
            username = (user_data.get('username') or username or '').lower().strip()
            first_name = user_data.get('first_name') or first_name or 'Пользователь'
            print(f"[AUTH] Валидация initData успешна: tg_id={tg_id}, username={username}")
        else:
            print(f"[AUTH] Валидация initData не прошла, используем данные напрямую")
    
    # Если tg_id всё ещё нет и включён тестовый режим — генерируем уникальный ID
    if not tg_id and TEST_MODE:
        # Генерируем уникальный tg_id на основе IP и времени для каждого пользователя
        client_ip = request.remote_addr or 'unknown'
        import hashlib
        unique_string = f"{client_ip}_{time.time()}_{random.random()}"
        tg_id = int(hashlib.md5(unique_string.encode()).hexdigest()[:9], 16) % 1000000000  # 9-значный ID
        tg_id = 1000000000 + tg_id  # Начинаем с 1 миллиарда для тестовых пользователей
        
        if not username:
            # Генерируем уникальный username
            username = f"user_{tg_id % 100000}"
        if not first_name:
            first_name = f'Пользователь {tg_id % 10000}'
        
        print(f"Тестовый режим: сгенерирован уникальный tg_id={tg_id}, username={username}")
    
    # В боевом режиме без tg_id — ошибка
    if not tg_id:
        return jsonify({'success': False, 'error': 'Не удалось получить данные пользователя (tg_id). Откройте через Telegram бота.'}), 400
    
    # Проверяем, что username не пустой (если пустой, генерируем)
    if not username or username.strip() == '':
        username = f"user_{tg_id % 100000}"
    
    username = username.lower().strip()
    
    conn = sqlite3.connect('wallet.db')
    c = conn.cursor()
    
    try:
        # Ищем пользователя по tg_id (основной идентификатор)
        c.execute("SELECT id, balance, banned, username FROM users WHERE tg_id = ?", (tg_id,))
        user = c.fetchone()
        
        if not user:
            # Создаём нового пользователя с уникальными данными
            wallet_address = generate_wallet_address()
            
            # Проверяем уникальность username, если занят - добавляем суффикс
            original_username = username
            username_counter = 1
            while True:
                c.execute("SELECT id FROM users WHERE username = ?", (username,))
                if not c.fetchone():
                    break
                username = f"{original_username}_{username_counter}"
                username_counter += 1
            
            c.execute("""
                INSERT INTO users (tg_id, username, first_name, balance, wallet_address)
                VALUES (?, ?, ?, 0.0, ?)
            """, (tg_id, username, first_name, wallet_address))
            conn.commit()
            user_id = c.lastrowid
            balance = 0.0
            print(f"✅ Создан новый пользователь: tg_id={tg_id}, user_id={user_id}, username={username}, balance={balance}")
        else:
            user_id, balance, banned, db_username = user
            if banned == 1:
                return jsonify({'success': False, 'error': 'Вы забанены'}), 403
            
            # Обновляем username и first_name, если они изменились
            if db_username != username or first_name:
                c.execute("UPDATE users SET username = ?, first_name = ? WHERE id = ?", 
                         (username, first_name, user_id))
                conn.commit()
            
            print(f"✅ Авторизован существующий пользователь: tg_id={tg_id}, user_id={user_id}, username={username}, balance={balance}")
        
        # Убеждаемся, что user_id установлен правильно
        if not user_id:
            return jsonify({'success': False, 'error': 'Ошибка получения ID пользователя'}), 500
        
        # Очищаем старую сессию и устанавливаем новую
        session.clear()
        session['user_id'] = user_id
        session['username'] = username
        session['first_name'] = first_name
        session['balance'] = balance
        
        print(f"Сессия установлена: user_id={session['user_id']}, username={session['username']}, balance={session['balance']}")
        
        return jsonify({'success': True, 'redirect': url_for('home')})
    except Exception as e:
        print(f"Ошибка авторизации: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сервера'}), 500
    finally:
        conn.close()

@app.route('/login', methods=['GET'])
def login():
    if 'user_id' in session:
        return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/home')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('wallet.db')
    c = conn.cursor()
    
    try:
        # Проверяем, что пользователь существует и получаем его данные
        c.execute("SELECT id, balance, tg_id, first_name FROM users WHERE id = ?", (user_id,))
        result = c.fetchone()
        
        if not result:
            print(f"Ошибка: пользователь с id={user_id} не найден в базе данных")
            session.clear()
            return redirect(url_for('login'))
        
        db_user_id, balance, tg_id, first_name = result
        
        # Дополнительная проверка - убеждаемся, что user_id из сессии совпадает с id из БД
        if db_user_id != user_id:
            print(f"Ошибка: несоответствие user_id. Сессия: {user_id}, БД: {db_user_id}")
            session.clear()
            return redirect(url_for('login'))
        
        balance = balance or 0.0
        first_name = first_name or session.get('first_name') or session.get('username', 'Пользователь')
        
        # Обновляем данные в сессии
        session['balance'] = balance
        session['first_name'] = first_name
        session['user_id'] = user_id  # Убеждаемся, что user_id правильный
        
        wallet_address = get_or_create_wallet_address(user_id)
        # Получаем аватарку только если это не тестовый пользователь
        avatar_url = None
        if tg_id and tg_id != 999999:
            try:
                avatar_url = get_user_avatar(tg_id)
            except Exception as e:
                print(f"Ошибка получения аватарки для tg_id {tg_id}: {e}")
                avatar_url = None
        
        # Получаем транзакции для конкретного пользователя
        c.execute("""
            SELECT transaction_type, amount, description, created_at
            FROM transactions
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 20
        """, (user_id,))
        
        transactions = []
        for row in c.fetchall():
            trans_type, amount, desc, created_at = row
            transactions.append({
                'type': trans_type,
                'amount': amount,
                'description': desc or '',
                'date': created_at
            })
        
        return render_template('home.html',
                             username=session['username'],
                             first_name=first_name,
                             balance=balance,
                             wallet_address=wallet_address,
                             transactions=transactions,
                             avatar_url=avatar_url)
    except Exception as e:
        print(f"Ошибка в home: {e}")
        return "Ошибка загрузки данных", 500
    finally:
        conn.close()

@app.route('/deposit', methods=['POST'])
def deposit():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'User ID not found in session'}), 401
    
    data = request.get_json()
    amount = float(data.get('amount', 0))
    
    if amount <= 0:
        return jsonify({'success': False, 'error': 'Неверная сумма'}), 400
    
    conn = sqlite3.connect('wallet.db')
    c = conn.cursor()
    
    try:
        # Проверяем, что пользователь существует
        c.execute("SELECT id FROM users WHERE id = ?", (user_id,))
        if not c.fetchone():
            return jsonify({'success': False, 'error': 'Пользователь не найден'}), 404
        
        c.execute("SELECT min_deposit, max_deposit FROM settings WHERE id = 1")
        min_dep, max_dep = c.fetchone()
        
        if amount < min_dep or amount > max_dep:
            return jsonify({
                'success': False,
                'error': f'Сумма должна быть от {min_dep:.2f} до {max_dep:.2f} ₽'
            }), 400
        
        c.execute("INSERT INTO deposit_requests (user_id, amount) VALUES (?, ?)", 
                  (user_id, amount))
        request_id = c.lastrowid
        conn.commit()
        
        c.execute("SELECT username, tg_id FROM users WHERE id = ?", (user_id,))
        user_data = c.fetchone()
        username = user_data[0] if user_data else 'unknown'
        user_tg_id = user_data[1] if user_data else None
        
        if user_tg_id:
            try:
                bot.send_message(
                    user_tg_id,
                    f"📥 <b>Заявка на пополнение создана!</b>\n\n"
                    f"💰 Сумма: <b>{amount:.2f} ₽</b>\n\n"
                    f"📍 Отправьте <b>{amount:.2f}</b> тортов на аккаунт:\n"
                    f"<code>@amaral</code>\n\n"
                    f"⏳ После отправки ожидайте подтверждения администратора.",
                    parse_mode='HTML'
                )
            except Exception as e:
                print(f"Ошибка отправки сообщения пользователю: {e}")
        
        try:
            bot.send_message(
                ADMIN_TG_ID,
                f"📥 <b>Новая заявка на пополнение!</b>\n\n"
                f"👤 Пользователь: @{username}\n"
                f"💰 Сумма: <b>{amount:.2f} ₽</b>\n"
                f"🆔 ID заявки: {request_id}\n\n"
                f"Для подтверждения: /confirm_{request_id}\n"
                f"Для отклонения: /reject_{request_id}",
                parse_mode='HTML'
            )
        except Exception as e:
            print(f"Ошибка отправки уведомления админу: {e}")
        
        return jsonify({
            'success': True,
            'message': f'Заявка создана! Отправьте {amount:.2f} тортов на @amaral и ожидайте подтверждения.'
        })
    except Exception as e:
        print(f"Ошибка в deposit: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сервера'}), 500
    finally:
        conn.close()

@app.route('/transfer', methods=['POST'])
def transfer():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'User ID not found in session'}), 401
    
    data = request.get_json()
    recipient_address = data.get('recipient_address', '').strip()
    amount = float(data.get('amount', 0))
    description = data.get('description', '')
    
    if not recipient_address:
        return jsonify({'success': False, 'error': 'Введите адрес получателя'}), 400
    
    if amount <= 0:
        return jsonify({'success': False, 'error': 'Неверная сумма'}), 400
    
    conn = sqlite3.connect('wallet.db')
    c = conn.cursor()
    
    try:
        # Проверяем баланс отправителя по его user_id
        c.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
        sender_result = c.fetchone()
        if not sender_result:
            return jsonify({'success': False, 'error': 'Отправитель не найден'}), 404
        
        sender_balance = sender_result[0] or 0.0
        
        if sender_balance < amount:
            return jsonify({'success': False, 'error': 'Недостаточно средств'}), 400
        
        c.execute("SELECT id, username, tg_id FROM users WHERE wallet_address = ?", (recipient_address,))
        recipient = c.fetchone()
        
        if not recipient:
            return jsonify({'success': False, 'error': 'Адрес получателя не найден'}), 404
        
        recipient_id, recipient_username, recipient_tg_id = recipient
        
        if recipient_id == user_id:
            return jsonify({'success': False, 'error': 'Нельзя переводить самому себе'}), 400
        
        c.execute("SELECT wallet_address FROM users WHERE id = ?", (user_id,))
        sender_address_result = c.fetchone()
        sender_address = sender_address_result[0] if sender_address_result else None
        
        # Обновляем балансы по правильным user_id
        c.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (amount, user_id))
        c.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, recipient_id))
        
        desc_sender = f'Перевод пользователю @{recipient_username}: {amount:.2f} ₽' + (f' ({description})' if description else '')
        desc_recipient = f'Перевод от @{session.get("username", "unknown")}: {amount:.2f} ₽' + (f' ({description})' if description else '')
        
        add_transaction(user_id, 'transfer_out', amount, desc_sender)
        add_transaction(recipient_id, 'transfer_in', amount, desc_recipient)
        
        conn.commit()
        
        # Получаем обновленный баланс отправителя
        c.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
        new_balance_result = c.fetchone()
        new_balance = new_balance_result[0] if new_balance_result else 0.0
        session['balance'] = new_balance
        
        if recipient_tg_id:
            try:
                bot.send_message(
                    recipient_tg_id,
                    f"💰 <b>Получен перевод!</b>\n\n"
                    f"Сумма: <b>{amount:.2f} ₽</b>\n"
                    f"От адреса: <code>{sender_address}</code>\n"
                    f"От пользователя: @{session.get('username', 'unknown')}\n"
                    f"{f'Комментарий: {description}' if description else ''}\n\n"
                    f"Ваш новый баланс будет обновлен на сайте.",
                    parse_mode='HTML'
                )
            except Exception as e:
                print(f"Ошибка отправки уведомления получателю: {e}")
        
        return jsonify({
            'success': True,
            'new_balance': new_balance,
            'message': f'✅ Успешно! Вы перевели {amount:.2f} ₽ на адрес {recipient_address}',
            'recipient_username': recipient_username
        })
    except Exception as e:
        print(f"Ошибка в transfer: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сервера'}), 500
    finally:
        conn.close()

@app.route('/transactions')
def transactions():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('wallet.db')
    c = conn.cursor()
    
    try:
        # Проверяем, что пользователь существует
        c.execute("SELECT id, username FROM users WHERE id = ?", (user_id,))
        user_result = c.fetchone()
        if not user_result:
            session.clear()
            return redirect(url_for('login'))
        
        db_user_id, db_username = user_result
        username = session.get('username') or db_username or 'Пользователь'
        
        # Получаем транзакции
        c.execute("""
            SELECT transaction_type, amount, description, created_at
            FROM transactions
            WHERE user_id = ?
            ORDER BY created_at DESC
        """, (user_id,))
        
        transactions = []
        for row in c.fetchall():
            trans_type, amount, desc, created_at = row
            transactions.append({
                'type': trans_type,
                'amount': float(amount) if amount else 0.0,
                'description': desc or '',
                'date': created_at or ''
            })
        
        print(f"[TRANSACTIONS] Загружено транзакций для user_id={user_id}: {len(transactions)}")
        
        return render_template('transactions.html',
                             username=username,
                             transactions=transactions)
    except Exception as e:
        print(f"Ошибка в transactions: {e}")
        import traceback
        traceback.print_exc()
        return "Ошибка загрузки данных", 500
    finally:
        conn.close()

@app.route('/admin')
def admin_panel():
    if not session.get('admin'):
        return redirect(url_for('login'))
    return render_template('admin.html')

@app.route('/admin/get_data', methods=['GET'])
def admin_get_data():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    conn = sqlite3.connect('wallet.db')
    c = conn.cursor()
    
    try:
        c.execute("SELECT min_deposit, max_deposit, min_withdraw, max_withdraw FROM settings WHERE id = 1")
        settings = c.fetchone()
        
        c.execute("SELECT tg_id, username, first_name, balance, banned, created_at FROM users")
        users = []
        for row in c.fetchall():
            users.append({
                'tg_id': row[0],
                'username': row[1] or '',
                'first_name': row[2] or '',
                'balance': row[3],
                'banned': row[4],
                'created_at': row[5]
            })
        
        c.execute("""
            SELECT u.tg_id, u.username, t.transaction_type, t.amount, t.description, t.created_at
            FROM transactions t
            JOIN users u ON t.user_id = u.id
            ORDER BY t.created_at DESC
            LIMIT 100
        """)
        
        transactions = []
        for row in c.fetchall():
            transactions.append({
                'tg_id': row[0],
                'username': row[1] or '',
                'type': row[2],
                'amount': row[3],
                'description': row[4] or '',
                'date': row[5]
            })
        
        return jsonify({
            'success': True,
            'settings': {
                'min_deposit': settings[0],
                'max_deposit': settings[1],
                'min_withdraw': settings[2],
                'max_withdraw': settings[3]
            },
            'users': users,
            'transactions': transactions
        })
    except Exception as e:
        print(f"Ошибка в admin_get_data: {e}")
        return jsonify({'success': False, 'error': 'Server error'}), 500
    finally:
        conn.close()

@app.route('/admin/give_balance', methods=['POST'])
def admin_give_balance():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    tg_id = data.get('tg_id')
    amount = float(data.get('amount', 0))
    
    if amount <= 0:
        return jsonify({'success': False, 'error': 'Неверная сумма'}), 400
    
    conn = sqlite3.connect('wallet.db')
    c = conn.cursor()
    
    try:
        c.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
        user = c.fetchone()
        
        if not user:
            return jsonify({'success': False, 'error': 'Пользователь не найден'}), 404
        
        user_id = user[0]
        c.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user_id))
        add_transaction(user_id, 'admin_give', amount, f'Выдача администратором: {amount:.2f} ₽')
        
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        print(f"Ошибка в admin_give_balance: {e}")
        return jsonify({'success': False, 'error': 'Server error'}), 500
    finally:
        conn.close()

@app.route('/admin/ban_user', methods=['POST'])
def admin_ban_user():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    tg_id = data.get('tg_id')
    
    conn = sqlite3.connect('wallet.db')
    c = conn.cursor()
    
    try:
        c.execute("UPDATE users SET banned = 1 WHERE tg_id = ?", (tg_id,))
        conn.commit()
        
        try:
            bot.send_message(tg_id, "❌ Вы были забанены администратором.")
        except:
            pass
        
        return jsonify({'success': True})
    except Exception as e:
        print(f"Ошибка в admin_ban_user: {e}")
        return jsonify({'success': False, 'error': 'Server error'}), 500
    finally:
        conn.close()

@app.route('/admin/unban_user', methods=['POST'])
def admin_unban_user():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    tg_id = data.get('tg_id')
    
    conn = sqlite3.connect('wallet.db')
    c = conn.cursor()
    
    try:
        c.execute("UPDATE users SET banned = 0 WHERE tg_id = ?", (tg_id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        print(f"Ошибка в admin_unban_user: {e}")
        return jsonify({'success': False, 'error': 'Server error'}), 500
    finally:
        conn.close()

@app.route('/admin/update_settings', methods=['POST'])
def admin_update_settings():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    
    conn = sqlite3.connect('wallet.db')
    c = conn.cursor()
    
    try:
        c.execute("""
            UPDATE settings SET
                min_deposit = ?,
                max_deposit = ?,
                min_withdraw = ?,
                max_withdraw = ?
            WHERE id = 1
        """, (
            float(data.get('min_deposit', 10)),
            float(data.get('max_deposit', 100000)),
            float(data.get('min_withdraw', 50)),
            float(data.get('max_withdraw', 50000))
        ))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        print(f"Ошибка в admin_update_settings: {e}")
        return jsonify({'success': False, 'error': 'Server error'}), 500
    finally:
        conn.close()

def run_bot():
    print("Запуск Telegram бота...")
    while True:
        try:
            bot.infinity_polling(skip_pending=True)
        except Exception as e:
            print(f"Ошибка в боте: {e}")
            try:
                bot.stop_polling()
            except:
                pass
            wait_time = 60 if "409" in str(e) else 20
            print(f"Перезапуск бота через {wait_time} секунд...")
            time.sleep(wait_time)

if __name__ == '__main__':
    print("Инициализация приложения...")
    init_db()
    
    t = threading.Thread(target=run_bot)
    t.daemon = True
    t.start()
    
    print("Запуск веб-сервера на http://0.0.0.0:1218")
    app.run(host='0.0.0.0', port=1218, debug=False)
