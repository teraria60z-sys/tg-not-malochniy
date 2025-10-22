import os
import telebot
from telebot import types
import sqlite3
import time
import threading
import schedule
from datetime import datetime
import logging
import json

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Конфигурация из переменных окружения
TOKEN = os.environ.get('BOT_TOKEN', '8255905138:AAG6jeN13ZuAH3zUrSJWHVGFLE9pmpTLFd8')
ADMIN_ID = 7607383500
MANAGER_USERNAME = '@Manager_molochniyshop'
ADMIN_PASSWORD = "шуруп_спасибо_за_шавуху"

bot = telebot.TeleBot(TOKEN)

# Сдельная система оплаты
PIECE_RATE_SYSTEM = {
    'pr_manager': {
        'rate_per_view': 5,
        'rate_per_client': 500,
        'bonus_threshold': 10
    },
    'poster': {
        'rate_per_post': 300,
        'rate_per_engagement': 50,
        'quality_bonus': 200
    },
    'gamer': {
        'rate_per_escort': 1000,
        'rate_per_review': 200,
        'safety_bonus': 300
    }
}

# Безопасная отправка сообщений
def safe_send_message(chat_id, text, **kwargs):
    try:
        return bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения {chat_id}: {e}")
        return None

# Инициализация базы данных
def init_db():
    try:
        conn = sqlite3.connect('bot_database.db', check_same_thread=False)
        cursor = conn.cursor()
        
        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                role TEXT DEFAULT 'user',
                referral_id TEXT,
                registration_date TEXT,
                banned_from_admin INTEGER DEFAULT 0,
                total_earned INTEGER DEFAULT 0,
                experience TEXT DEFAULT 'Нет опыта',
                skills TEXT DEFAULT 'Не указаны',
                last_payment_date TEXT,
                rating REAL DEFAULT 0.0,
                reviews_count INTEGER DEFAULT 0,
                is_admin INTEGER DEFAULT 0,
                contact_info TEXT DEFAULT 'Не указано'
            )
        ''')
        
        # Таблица заявок на вакансии
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS job_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                vacancy TEXT,
                experience TEXT,
                skills TEXT,
                about_me TEXT,
                application_text TEXT,
                status TEXT DEFAULT 'pending',
                application_date TEXT,
                admin_notes TEXT
            )
        ''')
        
        # Таблица транзакций
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                type TEXT,
                description TEXT,
                work_data TEXT,
                date TEXT,
                admin_id INTEGER,
                status TEXT DEFAULT 'completed'
            )
        ''')
        
        # Таблица отзывов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_user_id INTEGER,
                author_user_id INTEGER,
                rating INTEGER,
                comment TEXT,
                date TEXT,
                status TEXT DEFAULT 'pending'
            )
        ''')
        
        # Таблица работы сотрудников
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS work_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                work_type TEXT,
                quantity INTEGER,
                quality_metric REAL,
                description TEXT,
                date TEXT,
                approved_by_admin INTEGER DEFAULT 0,
                amount_calculated INTEGER DEFAULT 0
            )
        ''')
        
        # Добавляем текущего админа в базу
        cursor.execute('INSERT OR IGNORE INTO users (user_id, is_admin, role) VALUES (?, 1, "admin")', (ADMIN_ID,))
        
        conn.commit()
        logger.info("✅ База данных успешно инициализирована")
        return conn
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        return None

# Инициализация БД
db_connection = init_db()

# Словари сессий
user_sessions = {}

class UserSession:
    def __init__(self, user_id):
        self.user_id = user_id
        self.state = None
        self.data = {}
        self.created_at = time.time()
    
    def set_state(self, state, data=None):
        self.state = state
        if data:
            self.data.update(data)
    
    def get_data(self, key=None):
        if key:
            return self.data.get(key)
        return self.data
    
    def update_data(self, **kwargs):
        self.data.update(kwargs)
    
    def clear(self):
        self.state = None
        self.data = {}

def get_session(user_id):
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession(user_id)
    return user_sessions[user_id]

def is_admin(user_id):
    try:
        cursor = db_connection.cursor()
        cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        return result and result[0] == 1
    except:
        return False

def safe_notify_admin(message):
    try:
        safe_send_message(ADMIN_ID, message, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка уведомления админа: {e}")

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def start_command(message):
    try:
        user_id = message.chat.id
        username = message.from_user.username
        first_name = message.from_user.first_name
        last_name = message.from_user.last_name
        
        # Реферальная система
        referral_id = None
        if len(message.text.split()) > 1:
            referral_id = message.text.split()[1]
        
        # Добавление пользователя в БД
        cursor = db_connection.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user_exists = cursor.fetchone()
        
        if not user_exists:
            registration_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                'INSERT INTO users (user_id, username, first_name, last_name, referral_id, registration_date) VALUES (?, ?, ?, ?, ?, ?)',
                (user_id, username, first_name, last_name, referral_id, registration_date)
            )
            db_connection.commit()
            
            # Уведомление админу
            try:
                ref_info = f" по реферальной ссылке от {referral_id}" if referral_id else " без реферальной ссылки"
                safe_notify_admin(f"🆕 Новый пользователь: @{username or 'без username'} (ID: {user_id}){ref_info}")
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления админу: {e}")
        
        # Проверка "Я не робот"
        show_verification(user_id)
        
    except Exception as e:
        logger.error(f"Ошибка в start_command: {e}")
        safe_send_message(message.chat.id, "❌ Произошла ошибка. Попробуйте позже.")

def show_verification(user_id):
    try:
        markup = types.InlineKeyboardMarkup()
        verify_button = types.InlineKeyboardButton("✅ Я не робот", callback_data="not_robot")
        markup.add(verify_button)
        
        safe_send_message(user_id, "🎉 Добро пожаловать в MOLOCHNIY BOTIK!\n\nДля продолжения подтвердите, что вы не робот:", reply_markup=markup)
    except Exception as e:
        logger.error(f"Ошибка в show_verification: {e}")

# Обработчик callback'ов
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        user_id = call.message.chat.id
        session = get_session(user_id)
        
        if call.data == "not_robot":
            handle_verification(call)
        elif call.data == "metro_shop":
            show_metro_shop(user_id, call.message.message_id)
        elif call.data == "write_manager":
            show_manager_contact(user_id, call.message.message_id)
        elif call.data == "become_escort":
            show_vacancies(user_id, call.message.message_id)
        elif call.data == "back_to_main":
            show_main_menu(user_id)
        elif call.data == "profile":
            show_user_profile(user_id)
        elif call.data == "my_earnings":
            show_my_earnings(user_id)
        elif call.data == "my_reviews":
            show_my_reviews(user_id)
        elif call.data == "leave_review":
            start_review_process(user_id)
        elif call.data == "contact_manager":
            show_manager_contact(user_id)
        elif call.data in ["pr_manager_vacancy", "gamer_vacancy", "poster_vacancy"]:
            handle_vacancy_selection(call)
        elif call.data.startswith("admin_"):
            handle_admin_callback(call)
        elif call.data.startswith("review_"):
            handle_review_callback(call)
        elif call.data.startswith("salary_"):
            handle_salary_callback(call)
        elif call.data == "my_applications":
            show_my_applications(user_id)
        elif call.data == "admin_panel":
            if is_admin(user_id):
                show_admin_panel(user_id)
            else:
                bot.answer_callback_query(call.id, "❌ У вас нет прав доступа")
        elif call.data == "transfer_admin":
            start_transfer_admin(user_id)
        else:
            logger.warning(f"Неизвестный callback: {call.data}")
            
    except Exception as e:
        logger.error(f"Ошибка в callback_handler: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Произошла ошибка")
        except:
            pass

def handle_verification(call):
    try:
        user_id = call.message.chat.id
        welcome_text = "✅ Проверка пройдена! Добро пожаловать в MOLOCHNIY BOTIK!\n\n"
        
        cursor = db_connection.cursor()
        cursor.execute('SELECT referral_id FROM users WHERE user_id = ?', (user_id,))
        user_data = cursor.fetchone()
        
        if user_data and user_data[0]:
            welcome_text += f"👥 Вы были приглашены пользователем: {user_data[0]}\n\n"
        else:
            welcome_text += "👤 Вы перешли без реферальной ссылки\n\n"
        
        welcome_text += "🔄 Переходим на главную страницу..."
        bot.edit_message_text(chat_id=user_id, message_id=call.message.message_id, text=welcome_text)
        
        time.sleep(2)
        show_main_menu(user_id)
    except Exception as e:
        logger.error(f"Ошибка в handle_verification: {e}")

def show_main_menu(user_id, message_id=None):
    try:
        main_text = """🍞 *Привет! Влетаем в сферу метро шопа буквально с двух ног* 🍞

*Что мы вам гарантируем?*
• Достаточно низкие цены ✅
• Приятные, общительные, смешные и успешные сопроводы ✅

*Самое главное для нас это чтобы наши покупатели были довольны* 🤗"""

        markup = types.InlineKeyboardMarkup(row_width=1)
        
        metro_shop_btn = types.InlineKeyboardButton("🛍️ Переход в метро шоп", callback_data="metro_shop")
        manager_btn = types.InlineKeyboardButton("👨‍💼 Написать менеджеру", callback_data="write_manager")
        escort_btn = types.InlineKeyboardButton("💼 Вступить в ряды сопровожчиков", callback_data="become_escort")
        profile_btn = types.InlineKeyboardButton("👤 Мой профиль", callback_data="profile")
        contact_btn = types.InlineKeyboardButton("💬 Связаться с менеджером", callback_data="contact_manager")
        
        # Добавляем кнопку админ-панели для админа
        if is_admin(user_id):
            admin_btn = types.InlineKeyboardButton("👑 Админ панель", callback_data="admin_panel")
            markup.add(admin_btn)
        
        markup.add(metro_shop_btn, manager_btn, escort_btn, profile_btn, contact_btn)
        
        if message_id:
            bot.edit_message_text(chat_id=user_id, message_id=message_id, text=main_text, reply_markup=markup, parse_mode="Markdown")
        else:
            safe_send_message(user_id, main_text, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в show_main_menu: {e}")

def show_metro_shop(user_id, message_id=None):
    try:
        markup = types.InlineKeyboardMarkup()
        shop_button = types.InlineKeyboardButton("🛒 Перейти в Metro Shop", url="https://t.me/molochniyshop")
        back_button = types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")
        contact_button = types.InlineKeyboardButton("💬 Связаться с менеджером", callback_data="contact_manager")
        
        markup.add(shop_button)
        markup.add(contact_button)
        markup.add(back_button)
        
        text = "🎯 *Metro Shop* - ваш надежный партнер в мире покупок!\n\nНажмите кнопку ниже для перехода в наш магазин:"
        
        if message_id:
            bot.edit_message_text(chat_id=user_id, message_id=message_id, text=text, reply_markup=markup, parse_mode="Markdown")
        else:
            safe_send_message(user_id, text, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в show_metro_shop: {e}")

def show_manager_contact(user_id, message_id=None):
    try:
        contact_text = """💬 *Связь с менеджером*

По всем вопросам обращайтесь к нашему менеджеру - он всегда на связи и готов помочь!"""

        markup = types.InlineKeyboardMarkup()
        manager_button = types.InlineKeyboardButton("💬 Написать менеджеру", url=f"https://t.me/{MANAGER_USERNAME[1:]}")
        back_button = types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")
        
        markup.add(manager_button)
        markup.add(back_button)
        
        if message_id:
            bot.edit_message_text(chat_id=user_id, message_id=message_id, text=contact_text, reply_markup=markup, parse_mode="Markdown")
        else:
            safe_send_message(user_id, contact_text, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в show_manager_contact: {e}")

def show_vacancies(user_id, message_id=None):
    try:
        vacancies_text = """🚀 *Доступные вакансии в нашей команде!*

*Мы ищем талантливых людей в следующие отделы:*

1. *📊 Пиар-менеджер* 
   - Привлечение клиентов через социальные сети
   - Работа с реферальной системой
   - *Оплата:* Сдельная (за просмотры + привлеченных клиентов)

2. *🎮 Игрок (ответственный за сопроводы)*
   - Проведение сопроводов в метро
   - Обеспечение безопасности сделок
   - *Оплата:* Сдельная (за сопроводы + отзывы клиентов)

3. *📢 Постер (рекламщик)*
   - Создание и размещение рекламного контента
   - Ведение каналов и групп
   - *Оплата:* Сдельная (за посты + вовлечение)

💪 *Готовы присоединиться к нашей команде?* Выбирайте вакансию ниже!"""

        markup = types.InlineKeyboardMarkup(row_width=1)
        
        pr_manager_btn = types.InlineKeyboardButton("📊 Пиар-менеджер (сдельная)", callback_data="pr_manager_vacancy")
        gamer_btn = types.InlineKeyboardButton("🎮 Игрок-сопровод (сдельная)", callback_data="gamer_vacancy")
        poster_btn = types.InlineKeyboardButton("📢 Постер-рекламщик (сдельная)", callback_data="poster_vacancy")
        contact_btn = types.InlineKeyboardButton("💬 Вопросы по вакансиям", callback_data="contact_manager")
        back_button = types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")
        
        markup.add(pr_manager_btn, gamer_btn, poster_btn, contact_btn, back_button)
        
        if message_id:
            bot.edit_message_text(chat_id=user_id, message_id=message_id, text=vacancies_text, reply_markup=markup, parse_mode="Markdown")
        else:
            safe_send_message(user_id, vacancies_text, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в show_vacancies: {e}")

def handle_vacancy_selection(call):
    try:
        user_id = call.message.chat.id
        session = get_session(user_id)
        
        vacancy_map = {
            "pr_manager_vacancy": "Пиар-менеджер",
            "gamer_vacancy": "Игрок (сопровод)", 
            "poster_vacancy": "Постер (рекламщик)"
        }
        vacancy = vacancy_map[call.data]
        
        session.set_state('APPLYING_FOR_JOB', {'vacancy': vacancy})
        start_job_application(user_id)
    except Exception as e:
        logger.error(f"Ошибка в handle_vacancy_selection: {e}")

def start_job_application(user_id):
    try:
        session = get_session(user_id)
        vacancy = session.get_data('vacancy')
        
        session.set_state('APPLYING_EXPERIENCE', {'vacancy': vacancy})
        
        safe_send_message(user_id, f"📝 *Подача заявки на вакансию: {vacancy}*\n\nРасскажите о своем опыте работы:\n- Где работали раньше?\n- Какой у вас стаж?\n- Каких результатов достигли?", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в start_job_application: {e}")

# Обработчик команды /profile
@bot.message_handler(commands=['profile'])
def profile_command(message):
    try:
        user_id = message.chat.id
        show_user_profile(user_id)
    except Exception as e:
        logger.error(f"Ошибка в profile_command: {e}")

def show_user_profile(user_id):
    try:
        cursor = db_connection.cursor()
        cursor.execute('''
            SELECT username, first_name, last_name, role, registration_date, 
                   total_earned, experience, skills, rating, reviews_count, contact_info, is_admin
            FROM users WHERE user_id = ?
        ''', (user_id,))
        user_data = cursor.fetchone()
        
        if user_data:
            username, first_name, last_name, role, reg_date, total_earned, experience, skills, rating, reviews_count, contact_info, is_admin_flag = user_data
            
            profile_text = f"""👤 *Ваш профиль*

*Имя:* {first_name or 'Не указано'} {last_name or ''}
*Username:* @{username or 'Не указан'}
*Роль:* {role or 'Пользователь'}
*Дата регистрации:* {reg_date}
*Рейтинг:* {rating:.1f}/5 ⭐
*Количество отзывов:* {reviews_count}"""

            if is_admin_flag:
                profile_text += "\n*Статус:* 👑 Администратор"

            if role != 'user':
                profile_text += f"\n*Всего заработано:* {total_earned or 0:,}₽"
                profile_text += f"\n*Опыт:* {experience}"
                profile_text += f"\n*Навыки:* {skills}"

            markup = types.InlineKeyboardMarkup(row_width=2)
            
            if role != 'user':
                earnings_btn = types.InlineKeyboardButton("💰 Мои заработки", callback_data="my_earnings")
                reviews_btn = types.InlineKeyboardButton("⭐ Мои отзывы", callback_data="my_reviews")
                applications_btn = types.InlineKeyboardButton("📋 Мои заявки", callback_data="my_applications")
                markup.add(earnings_btn, reviews_btn, applications_btn)
            
            if is_admin_flag:
                admin_btn = types.InlineKeyboardButton("👑 Админ панель", callback_data="admin_panel")
                markup.add(admin_btn)
            
            leave_review_btn = types.InlineKeyboardButton("📝 Оставить отзыв", callback_data="leave_review")
            contact_btn = types.InlineKeyboardButton("💬 Связаться с менеджером", callback_data="contact_manager")
            back_btn = types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")
            
            markup.add(leave_review_btn, contact_btn, back_btn)
            
            safe_send_message(user_id, profile_text, reply_markup=markup, parse_mode="Markdown")
        else:
            safe_send_message(user_id, "❌ Профиль не найден.")
    except Exception as e:
        logger.error(f"Ошибка в show_user_profile: {e}")

def show_my_earnings(user_id):
    try:
        cursor = db_connection.cursor()
        cursor.execute('SELECT role, total_earned FROM users WHERE user_id = ?', (user_id,))
        user_data = cursor.fetchone()
        
        if not user_data or user_data[0] == 'user':
            safe_send_message(user_id, "❌ У вас нет доступа к этой функции.")
            return
        
        role, total_earned = user_data
        
        # Получаем последние транзакции
        cursor.execute('''
            SELECT amount, type, description, date 
            FROM transactions 
            WHERE user_id = ? 
            ORDER BY date DESC 
            LIMIT 10
        ''', (user_id,))
        transactions = cursor.fetchall()
        
        earnings_text = f"""💰 *Ваши заработки*

*Должность:* {role}
*Всего заработано:* {total_earned or 0:,}₽"""

        if transactions:
            earnings_text += "\n\n*Последние выплаты:*"
            for amount, trans_type, description, date in transactions:
                earnings_text += f"\n• {date}: {amount:,}₽ ({description})"
        else:
            earnings_text += "\n\n*Пока нет выплат*"
        
        # Информация о сдельной системе
        if role in PIECE_RATE_SYSTEM:
            rates = PIECE_RATE_SYSTEM[role]
            earnings_text += "\n\n*Тарифы сдельной оплаты:*"
            if role == 'pr_manager':
                earnings_text += f"\n• За 1000 просмотров: {rates['rate_per_view']}₽"
                earnings_text += f"\n• За привлеченного клиента: {rates['rate_per_client']}₽"
            elif role == 'poster':
                earnings_text += f"\n• За пост: {rates['rate_per_post']}₽"
                earnings_text += f"\n• За 100 вовлечений: {rates['rate_per_engagement']}₽"
            elif role == 'gamer':
                earnings_text += f"\n• За сопровод: {rates['rate_per_escort']}₽"
                earnings_text += f"\n• Бонус за отзыв: {rates['rate_per_review']}₽"
        
        markup = types.InlineKeyboardMarkup()
        contact_btn = types.InlineKeyboardButton("💬 Вопросы по выплатам", callback_data="contact_manager")
        back_btn = types.InlineKeyboardButton("🔙 Назад", callback_data="profile")
        markup.add(contact_btn, back_btn)
        
        safe_send_message(user_id, earnings_text, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        logger.error(f"Ошибка в show_my_earnings: {e}")

def show_my_applications(user_id):
    try:
        cursor = db_connection.cursor()
        cursor.execute('''
            SELECT vacancy, application_text, status, application_date 
            FROM job_applications 
            WHERE user_id = ? 
            ORDER BY application_date DESC
        ''', (user_id,))
        applications = cursor.fetchall()
        
        if not applications:
            safe_send_message(user_id, "📭 У вас нет поданых заявок.")
            return
        
        apps_text = "📋 *Ваши заявки*\n\n"
        
        for i, (vacancy, app_text, status, app_date) in enumerate(applications, 1):
            status_icon = "✅" if status == "approved" else "❌" if status == "rejected" else "⏳"
            apps_text += f"{i}. *{vacancy}* {status_icon}\nДата: {app_date}\nСтатус: {status}\n\n"
        
        markup = types.InlineKeyboardMarkup()
        back_btn = types.InlineKeyboardButton("🔙 Назад", callback_data="profile")
        markup.add(back_btn)
        
        safe_send_message(user_id, apps_text, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        logger.error(f"Ошибка в show_my_applications: {e}")

def show_my_reviews(user_id):
    try:
        cursor = db_connection.cursor()
        
        # Отзывы о пользователе
        cursor.execute('''
            SELECT r.rating, r.comment, r.date, u.username 
            FROM reviews r 
            LEFT JOIN users u ON r.author_user_id = u.user_id 
            WHERE r.target_user_id = ? AND r.status = 'approved'
            ORDER BY r.date DESC
        ''', (user_id,))
        reviews = cursor.fetchall()
        
        reviews_text = "⭐ *Отзывы о вас*\n\n"
        
        if reviews:
            total_rating = 0
            for rating, comment, date, author in reviews:
                total_rating += rating
                stars = "⭐" * rating
                reviews_text += f"*{author or 'Аноним'}* {stars}\n"
                reviews_text += f"_{comment}_\n"
                reviews_text += f"📅 {date}\n\n"
            
            avg_rating = total_rating / len(reviews)
            reviews_text += f"*Средний рейтинг:* {avg_rating:.1f}/5 ⭐"
        else:
            reviews_text += "Пока нет отзывов о вашей работе."
        
        markup = types.InlineKeyboardMarkup()
        back_btn = types.InlineKeyboardButton("🔙 Назад", callback_data="profile")
        markup.add(back_btn)
        
        safe_send_message(user_id, reviews_text, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        logger.error(f"Ошибка в show_my_reviews: {e}")

def start_review_process(user_id):
    try:
        session = get_session(user_id)
        session.set_state('LEAVING_REVIEW_TARGET')
        
        # Получаем список сотрудников
        cursor = db_connection.cursor()
        cursor.execute('''
            SELECT user_id, username, first_name, role 
            FROM users 
            WHERE role != 'user' 
            ORDER BY role
        ''')
        employees = cursor.fetchall()
        
        if not employees:
            safe_send_message(user_id, "❌ В системе пока нет сотрудников для отзыва.")
            return
        
        review_text = "👥 *Выберите сотрудника для отзыва:*\n\n"
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        for emp in employees:
            emp_id, username, first_name, role = emp
            btn_text = f"{first_name or username} ({role})"
            markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"review_target_{emp_id}"))
        
        back_btn = types.InlineKeyboardButton("🔙 Назад", callback_data="profile")
        markup.add(back_btn)
        
        safe_send_message(user_id, review_text, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в start_review_process: {e}")

def handle_review_callback(call):
    try:
        user_id = call.message.chat.id
        session = get_session(user_id)
        
        if call.data.startswith("review_target_"):
            target_user_id = int(call.data.split("_")[2])
            session.set_state('LEAVING_REVIEW_RATING', {'target_user_id': target_user_id})
            
            markup = types.InlineKeyboardMarkup(row_width=5)
            for i in range(1, 6):
                markup.add(types.InlineKeyboardButton("⭐" * i, callback_data=f"review_rating_{i}"))
            
            back_btn = types.InlineKeyboardButton("🔙 Назад", callback_data="leave_review")
            markup.add(back_btn)
            
            bot.edit_message_text(chat_id=user_id, message_id=call.message.message_id,
                                 text="⭐ *Оцените работу сотрудника:*", reply_markup=markup, parse_mode="Markdown")
        
        elif call.data.startswith("review_rating_"):
            rating = int(call.data.split("_")[2])
            session.update_data(rating=rating)
            session.set_state('LEAVING_REVIEW_COMMENT')
            
            bot.edit_message_text(chat_id=user_id, message_id=call.message.message_id,
                                 text="📝 *Напишите комментарий к отзыву:*\n\nОпишите ваше впечатление о работе сотрудника:",
                                 parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в handle_review_callback: {e}")

# Обработчик текстовых сообщений
@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    try:
        user_id = message.chat.id
        text = message.text
        session = get_session(user_id)
        
        # Обработка пароля для админки
        if session.state == 'WAITING_ADMIN_PASSWORD':
            if text == ADMIN_PASSWORD:
                # Пароль верный - даем права админа
                cursor = db_connection.cursor()
                cursor.execute('UPDATE users SET is_admin = 1 WHERE user_id = ?', (user_id,))
                db_connection.commit()
                session.clear()
                safe_send_message(user_id, "✅ Пароль верный! Теперь у вас есть права администратора.")
                show_admin_panel(user_id)
            else:
                session.clear()
                safe_send_message(user_id, "❌ Неверный пароль!")
            return
        
        # Передача прав админа
        elif session.state == 'TRANSFER_ADMIN':
            try:
                new_admin_id = int(text)
                cursor = db_connection.cursor()
                
                # Проверяем существование пользователя
                cursor.execute('SELECT 1 FROM users WHERE user_id = ?', (new_admin_id,))
                if not cursor.fetchone():
                    safe_send_message(user_id, "❌ Пользователь с таким ID не найден.")
                    session.clear()
                    return
                
                # Убираем права у текущего админа
                cursor.execute('UPDATE users SET is_admin = 0 WHERE user_id = ?', (user_id,))
                # Даем права новому админу
                cursor.execute('UPDATE users SET is_admin = 1 WHERE user_id = ?', (new_admin_id,))
                db_connection.commit()
                
                session.clear()
                safe_send_message(user_id, f"✅ Права администратора успешно переданы пользователю {new_admin_id}!")
                
                # Уведомляем нового админа
                safe_send_message(new_admin_id, "🎉 Вам были предоставлены права администратора бота!")
                
            except ValueError:
                safe_send_message(user_id, "❌ Пожалуйста, введите корректный ID пользователя (только цифры).")
            except Exception as e:
                logger.error(f"Ошибка передачи прав: {e}")
                safe_send_message(user_id, "❌ Произошла ошибка при передаче прав.")
        
        # Подача заявки на вакансию
        elif session.state == 'APPLYING_EXPERIENCE':
            session.update_data(experience=text)
            session.set_state('APPLYING_SKILLS')
            safe_send_message(user_id, "🛠️ *Расскажите о своих навыках:*\n\n- Какими программами/инструментами владеете?\n- Какие у вас есть специальные навыки?", parse_mode="Markdown")
        
        elif session.state == 'APPLYING_SKILLS':
            session.update_data(skills=text)
            session.set_state('APPLYING_ABOUT')
            safe_send_message(user_id, "👨‍💼 *Расскажите о себе подробнее:*\n\n- Почему хотите работать именно у нас?\n- Какие у вас цели?", parse_mode="Markdown")
        
        elif session.state == 'APPLYING_ABOUT':
            session.update_data(about_me=text)
            session.set_state('APPLYING_FINAL')
            safe_send_message(user_id, "💬 *Напишите заключительное сообщение:*\n\n- Почему мы должны выбрать именно вас?", parse_mode="Markdown")
        
        elif session.state == 'APPLYING_FINAL':
            # ИСПРАВЛЕНИЕ: Проверяем наличие vacancy в данных сессии
            if 'vacancy' not in session.data:
                safe_send_message(user_id, "❌ Ошибка: вакансия не найдена. Начните заново.")
                session.clear()
                show_main_menu(user_id)
                return
                
            application_text = text
            vacancy = session.data['vacancy']
            experience = session.data['experience']
            skills = session.data['skills']
            about_me = session.data['about_me']
            
            # Сохраняем заявку
            cursor = db_connection.cursor()
            application_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                'INSERT INTO job_applications (user_id, vacancy, experience, skills, about_me, application_text, application_date) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (user_id, vacancy, experience, skills, about_me, application_text, application_date)
            )
            db_connection.commit()
            
            # Обновляем профиль
            cursor.execute('UPDATE users SET experience = ?, skills = ? WHERE user_id = ?',
                         (experience, skills, user_id))
            db_connection.commit()
            
            # Уведомление админу
            try:
                cursor.execute('SELECT username FROM users WHERE user_id = ?', (user_id,))
                username = cursor.fetchone()[0] or "без username"
                
                app_notification = f"""📨 *НОВАЯ ЗАЯВКА НА ВАКАНСИЮ*

*Вакансия:* {vacancy}
*Пользователь:* @{username} (ID: {user_id})

*Опыт:* {experience[:200]}...
*Навыки:* {skills[:200]}...
*О себе:* {about_me[:200]}...
*Заключение:* {application_text[:200]}..."""

                safe_notify_admin(app_notification)
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления: {e}")
            
            session.clear()
            safe_send_message(user_id, f"✅ Ваша заявка на вакансию *{vacancy}* отправлена! Мы свяжемся с вами.", parse_mode="Markdown")
            show_main_menu(user_id)
        
        # Оставление отзыва
        elif session.state == 'LEAVING_REVIEW_COMMENT':
            comment = text
            data = session.get_data()
            
            # Сохраняем отзыв
            cursor = db_connection.cursor()
            review_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                'INSERT INTO reviews (target_user_id, author_user_id, rating, comment, date) VALUES (?, ?, ?, ?, ?)',
                (data['target_user_id'], user_id, data['rating'], comment, review_date)
            )
            db_connection.commit()
            
            # Уведомление админу
            try:
                cursor.execute('SELECT username FROM users WHERE user_id = ?', (data['target_user_id'],))
                target_username = cursor.fetchone()[0] or "без username"
                
                cursor.execute('SELECT username FROM users WHERE user_id = ?', (user_id,))
                author_username = cursor.fetchone()[0] or "без username"
                
                review_notification = f"""⭐ *НОВЫЙ ОТЗЫВ*

*Автор:* @{author_username} (ID: {user_id})
*Сотрудник:* @{target_username} (ID: {data['target_user_id']})
*Оценка:* {'⭐' * data['rating']}
*Комментарий:* {comment}"""

                safe_notify_admin(review_notification)
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления об отзыве: {e}")
            
            session.clear()
            safe_send_message(user_id, "✅ Ваш отзыв сохранен и отправлен на модерацию!", parse_mode="Markdown")
            show_main_menu(user_id)
        
        # Обработка админ-команд
        elif session.state and session.state.startswith('ADMIN_'):
            handle_admin_text_input(user_id, text, session)
        
        else:
            show_main_menu(user_id)
            
    except Exception as e:
        logger.error(f"Ошибка в handle_messages: {e}")
        safe_send_message(message.chat.id, "❌ Произошла ошибка. Попробуйте позже.")

# АДМИН ПАНЕЛЬ
@bot.message_handler(commands=['admin'])
def admin_command(message):
    try:
        user_id = message.chat.id
        
        if is_admin(user_id):
            show_admin_panel(user_id)
        else:
            # Запрос пароля
            session = get_session(user_id)
            session.set_state('WAITING_ADMIN_PASSWORD')
            safe_send_message(user_id, "🔐 Введите пароль для доступа к админ-панели:")
    except Exception as e:
        logger.error(f"Ошибка в admin_command: {e}")

def show_admin_panel(user_id):
    try:
        if not is_admin(user_id):
            safe_send_message(user_id, "❌ У вас нет прав доступа к админ-панели.")
            return
            
        admin_text = "👑 *ПАНЕЛЬ АДМИНИСТРАТОРА*\n\n*Выберите раздел для управления:*"
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        users_btn = types.InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")
        applications_btn = types.InlineKeyboardButton("📋 Заявки", callback_data="admin_applications")
        reviews_btn = types.InlineKeyboardButton("⭐ Отзывы", callback_data="admin_reviews")
        salary_btn = types.InlineKeyboardButton("💰 Зарплаты", callback_data="admin_salary")
        stats_btn = types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
        broadcast_btn = types.InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")
        transfer_btn = types.InlineKeyboardButton("🔄 Передать права", callback_data="transfer_admin")
        
        markup.add(users_btn, applications_btn, reviews_btn, salary_btn, stats_btn, broadcast_btn, transfer_btn)
        
        safe_send_message(user_id, admin_text, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в show_admin_panel: {e}")

def start_transfer_admin(user_id):
    try:
        if not is_admin(user_id):
            return
            
        session = get_session(user_id)
        session.set_state('TRANSFER_ADMIN')
        safe_send_message(user_id, "🔄 *Передача прав администратора*\n\nВведите ID пользователя, которому хотите передать права администратора:")
    except Exception as e:
        logger.error(f"Ошибка в start_transfer_admin: {e}")

def handle_admin_callback(call):
    try:
        user_id = call.message.chat.id
        
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "❌ Нет доступа к админ-панели")
            return
        
        if call.data == "admin_users":
            show_admin_users(user_id)
        elif call.data == "admin_applications":
            show_admin_applications(user_id)
        elif call.data == "admin_reviews":
            show_admin_reviews(user_id)
        elif call.data == "admin_salary":
            show_admin_salary(user_id)
        elif call.data == "admin_stats":
            show_admin_stats(user_id)
        elif call.data == "admin_broadcast":
            start_broadcast(user_id)
        elif call.data == "admin_back":
            show_admin_panel(user_id)
        elif call.data.startswith("admin_user_"):
            user_action = call.data.split("_")[2]
            target_user_id = int(call.data.split("_")[3])
            handle_user_action(user_id, user_action, target_user_id)
        elif call.data.startswith("admin_application_"):
            app_action = call.data.split("_")[2]
            app_id = int(call.data.split("_")[3])
            handle_application_action(user_id, app_action, app_id)
        elif call.data.startswith("admin_review_"):
            review_action = call.data.split("_")[2]
            review_id = int(call.data.split("_")[3])
            handle_review_action(user_id, review_action, review_id)
        elif call.data == "transfer_admin":
            start_transfer_admin(user_id)
    except Exception as e:
        logger.error(f"Ошибка в handle_admin_callback: {e}")

def handle_salary_callback(call):
    try:
        user_id = call.message.chat.id
        
        if not is_admin(user_id):
            return
        
        if call.data.startswith("salary_pay_"):
            target_user_id = int(call.data.split("_")[2])
            session = get_session(user_id)
            session.set_state(f'ADMIN_PAY_SALARY_{target_user_id}')
            safe_send_message(user_id, f"💸 Введите сумму для выплаты пользователю {target_user_id}:")
        
        elif call.data.startswith("salary_set_"):
            target_user_id = int(call.data.split("_")[2])
            session = get_session(user_id)
            session.set_state(f'ADMIN_SET_SALARY_{target_user_id}')
            safe_send_message(user_id, f"⚙️ Введите новую зарплату для пользователя {target_user_id}:")
    except Exception as e:
        logger.error(f"Ошибка в handle_salary_callback: {e}")

def handle_admin_text_input(user_id, text, session):
    try:
        state = session.state
        
        if state.startswith('ADMIN_PAY_SALARY_'):
            target_user_id = int(state.split('_')[3])
            amount = int(text)
            
            cursor = db_connection.cursor()
            
            # Обновляем общий заработок
            cursor.execute('SELECT total_earned FROM users WHERE user_id = ?', (target_user_id,))
            current_total = cursor.fetchone()[0] or 0
            new_total = current_total + amount
            
            cursor.execute('UPDATE users SET total_earned = ?, last_payment_date = ? WHERE user_id = ?',
                         (new_total, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), target_user_id))
            
            # Записываем транзакцию
            trans_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                'INSERT INTO transactions (user_id, amount, type, description, date, admin_id) VALUES (?, ?, ?, ?, ?, ?)',
                (target_user_id, amount, 'salary', 'Выплата зарплаты', trans_date, user_id)
            )
            db_connection.commit()
            
            session.clear()
            safe_send_message(user_id, f"✅ Выплачено {amount:,}₽ пользователю {target_user_id}")
            
            # Уведомляем пользователя
            safe_send_message(target_user_id, f"🎉 Вам выплачена зарплата в размере {amount:,}₽!\n\nВаш общий заработок: {new_total:,}₽")
        
        elif state == 'ADMIN_BROADCAST':
            broadcast_text = text
            session.clear()
            
            # Рассылка всем пользователям
            cursor = db_connection.cursor()
            cursor.execute('SELECT user_id FROM users')
            all_users = cursor.fetchall()
            
            sent_count = 0
            failed_count = 0
            
            safe_send_message(user_id, f"📢 Начинаю рассылку для {len(all_users)} пользователей...")
            
            for user in all_users:
                try:
                    user_id_db = user[0]
                    safe_send_message(user_id_db, f"📢 *Сообщение от администратора:*\n\n{broadcast_text}", parse_mode="Markdown")
                    sent_count += 1
                    time.sleep(0.1)
                except:
                    failed_count += 1
            
            safe_send_message(user_id, f"✅ Рассылка завершена!\n\nУспешно: {sent_count}\nНе удалось: {failed_count}")
    
    except ValueError:
        safe_send_message(user_id, "❌ Пожалуйста, введите корректную сумму (только цифры)")
    except Exception as e:
        logger.error(f"Ошибка в handle_admin_text_input: {e}")
        safe_send_message(user_id, "❌ Произошла ошибка при обработке запроса")

def show_admin_users(user_id):
    try:
        cursor = db_connection.cursor()
        cursor.execute('''
            SELECT user_id, username, first_name, role, registration_date, is_admin
            FROM users 
            ORDER BY registration_date DESC 
            LIMIT 20
        ''')
        users = cursor.fetchall()
        
        users_text = "👥 *Последние 20 пользователей*\n\n"
        
        for user in users:
            user_id_db, username, first_name, role, reg_date, is_admin_flag = user
            admin_status = " 👑" if is_admin_flag else ""
            users_text += f"ID: {user_id_db} | @{username or 'нет'} | {role}{admin_status}\n"
        
        markup = types.InlineKeyboardMarkup()
        back_btn = types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back")
        markup.add(back_btn)
        
        safe_send_message(user_id, users_text, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в show_admin_users: {e}")

def show_admin_applications(user_id):
    try:
        cursor = db_connection.cursor()
        cursor.execute('''
            SELECT id, user_id, vacancy, application_date 
            FROM job_applications 
            WHERE status = 'pending'
            ORDER BY application_date DESC
        ''')
        applications = cursor.fetchall()
        
        if not applications:
            safe_send_message(user_id, "✅ Нет заявок, ожидающих рассмотрения.")
            return
        
        apps_text = "📋 *Заявки на рассмотрении*\n\n"
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        for app in applications:
            app_id, app_user_id, vacancy, app_date = app
            apps_text += f"*Заявка #{app_id}*\nВакансия: {vacancy}\nПользователь: {app_user_id}\nДата: {app_date}\n\n"
            
            approve_btn = types.InlineKeyboardButton(f"✅ #{app_id}", callback_data=f"admin_application_approve_{app_id}")
            reject_btn = types.InlineKeyboardButton(f"❌ #{app_id}", callback_data=f"admin_application_reject_{app_id}")
            markup.add(approve_btn, reject_btn)
        
        back_btn = types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back")
        markup.add(back_btn)
        
        safe_send_message(user_id, apps_text, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в show_admin_applications: {e}")

def show_admin_reviews(user_id):
    try:
        cursor = db_connection.cursor()
        cursor.execute('''
            SELECT r.id, r.target_user_id, r.author_user_id, r.rating, r.comment, r.date,
                   u1.username as target_username, u2.username as author_username
            FROM reviews r
            LEFT JOIN users u1 ON r.target_user_id = u1.user_id
            LEFT JOIN users u2 ON r.author_user_id = u2.user_id
            WHERE r.status = 'pending'
            ORDER BY r.date DESC
        ''')
        reviews = cursor.fetchall()
        
        if not reviews:
            safe_send_message(user_id, "✅ Нет отзывов на модерации.")
            return
        
        reviews_text = "⭐ *Отзывы на модерации*\n\n"
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        for review in reviews:
            review_id, target_id, author_id, rating, comment, date, target_user, author_user = review
            reviews_text += f"*Отзыв #{review_id}*\nОценка: {'⭐' * rating}\nАвтор: @{author_user or author_id}\nСотрудник: @{target_user or target_id}\nДата: {date}\n\n"
            
            approve_btn = types.InlineKeyboardButton(f"✅ #{review_id}", callback_data=f"admin_review_approve_{review_id}")
            reject_btn = types.InlineKeyboardButton(f"❌ #{review_id}", callback_data=f"admin_review_reject_{review_id}")
            markup.add(approve_btn, reject_btn)
        
        back_btn = types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back")
        markup.add(back_btn)
        
        safe_send_message(user_id, reviews_text, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в show_admin_reviews: {e}")

def show_admin_salary(user_id):
    try:
        cursor = db_connection.cursor()
        cursor.execute('''
            SELECT user_id, username, first_name, role, total_earned 
            FROM users 
            WHERE role != 'user' 
            ORDER BY total_earned DESC
        ''')
        employees = cursor.fetchall()
        
        if not employees:
            safe_send_message(user_id, "❌ Нет сотрудников с назначенными ролями.")
            return
        
        salary_text = "💰 *УПРАВЛЕНИЕ ЗАРПЛАТАМИ*\n\n*Список сотрудников:*\n\n"
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        for emp in employees:
            emp_id, username, first_name, role, total_earned = emp
            salary_text += f"*{first_name or username}* (ID: {emp_id})\n"
            salary_text += f"Должность: {role}\n"
            salary_text += f"Всего заработано: {total_earned or 0:,}₽\n\n"
            
            # Кнопки для управления зарплатой
            pay_btn = types.InlineKeyboardButton(f"💸 {emp_id}", callback_data=f"salary_pay_{emp_id}")
            markup.add(pay_btn)
        
        back_btn = types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back")
        markup.add(back_btn)
        
        safe_send_message(user_id, salary_text, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в show_admin_salary: {e}")

def show_admin_stats(user_id):
    try:
        cursor = db_connection.cursor()
        
        # Общее количество пользователей
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        
        # Количество пользователей по ролям
        cursor.execute('SELECT role, COUNT(*) FROM users GROUP BY role')
        roles_stats = cursor.fetchall()
        
        # Количество заявок
        cursor.execute('SELECT COUNT(*) FROM job_applications')
        total_applications = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM job_applications WHERE status = "pending"')
        pending_applications = cursor.fetchone()[0]
        
        # Общая сумма выплат
        cursor.execute('SELECT SUM(amount) FROM transactions WHERE type = "salary"')
        total_payments = cursor.fetchone()[0] or 0
        
        stats_text = f"""📊 *СТАТИСТИКА БОТА*

*Пользователи:*
• Всего: {total_users}"""

        for role, count in roles_stats:
            stats_text += f"\n• {role or 'user'}: {count}"
        
        stats_text += f"""

*Заявки на вакансии:*
• Всего: {total_applications}
• Ожидают рассмотрения: {pending_applications}

*Финансы:*
• Всего выплачено: {total_payments:,}₽"""
        
        markup = types.InlineKeyboardMarkup()
        back_btn = types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back")
        markup.add(back_btn)
        
        safe_send_message(user_id, stats_text, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в show_admin_stats: {e}")

def start_broadcast(user_id):
    try:
        session = get_session(user_id)
        session.set_state('ADMIN_BROADCAST')
        safe_send_message(user_id, "📢 Введите сообщение для рассылки всем пользователям:")
    except Exception as e:
        logger.error(f"Ошибка в start_broadcast: {e}")

def handle_user_action(admin_id, action, target_user_id):
    try:
        if action == "profile":
            cursor = db_connection.cursor()
            cursor.execute('SELECT username, first_name, role FROM users WHERE user_id = ?', (target_user_id,))
            user_data = cursor.fetchone()
            
            if user_data:
                username, first_name, role = user_data
                safe_send_message(admin_id, f"👤 *Профиль пользователя*\n\nID: {target_user_id}\nИмя: {first_name}\nUsername: @{username or 'нет'}\nРоль: {role}", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в handle_user_action: {e}")

def handle_application_action(admin_id, action, app_id):
    try:
        cursor = db_connection.cursor()
        
        if action == "approve":
            cursor.execute('UPDATE job_applications SET status = "approved" WHERE id = ?', (app_id,))
            
            # Получаем информацию о заявке
            cursor.execute('SELECT user_id, vacancy FROM job_applications WHERE id = ?', (app_id,))
            app_data = cursor.fetchone()
            
            if app_data:
                target_user_id, vacancy = app_data
                
                # Устанавливаем роль пользователя
                role_mapping = {
                    "Пиар-менеджер": "pr_manager",
                    "Игрок (сопровод)": "gamer", 
                    "Постер (рекламщик)": "poster"
                }
                
                new_role = role_mapping.get(vacancy, "user")
                cursor.execute('UPDATE users SET role = ? WHERE user_id = ?', (new_role, target_user_id))
                
                # Уведомляем пользователя
                safe_send_message(target_user_id, f"🎉 Поздравляем! Ваша заявка на вакансию '{vacancy}' одобрена! Теперь ваша роль: {new_role}")
            
            db_connection.commit()
            safe_send_message(admin_id, f"✅ Заявка #{app_id} одобрена!")
        
        elif action == "reject":
            cursor.execute('UPDATE job_applications SET status = "rejected" WHERE id = ?', (app_id,))
            db_connection.commit()
            
            # Уведомляем пользователя
            cursor.execute('SELECT user_id, vacancy FROM job_applications WHERE id = ?', (app_id,))
            app_data = cursor.fetchone()
            
            if app_data:
                target_user_id, vacancy = app_data
                safe_send_message(target_user_id, f"❌ К сожалению, ваша заявка на вакансию '{vacancy}' была отклонена.")
            
            safe_send_message(admin_id, f"❌ Заявка #{app_id} отклонена!")
        
        show_admin_applications(admin_id)
    except Exception as e:
        logger.error(f"Ошибка в handle_application_action: {e}")

def handle_review_action(admin_id, action, review_id):
    try:
        cursor = db_connection.cursor()
        
        if action == "approve":
            cursor.execute('UPDATE reviews SET status = "approved" WHERE id = ?', (review_id,))
            
            # Обновляем рейтинг пользователя
            cursor.execute('SELECT target_user_id, rating FROM reviews WHERE id = ?', (review_id,))
            review_data = cursor.fetchone()
            
            if review_data:
                target_user_id, rating = review_data
                
                # Получаем текущий рейтинг и количество отзывов
                cursor.execute('SELECT rating, reviews_count FROM users WHERE user_id = ?', (target_user_id,))
                user_data = cursor.fetchone()
                
                if user_data:
                    current_rating, current_count = user_data
                    new_count = current_count + 1
                    new_rating = ((current_rating * current_count) + rating) / new_count
                    
                    cursor.execute('UPDATE users SET rating = ?, reviews_count = ? WHERE user_id = ?',
                                 (new_rating, new_count, target_user_id))
            
            db_connection.commit()
            safe_send_message(admin_id, f"✅ Отзыв #{review_id} одобрен!")
        
        elif action == "reject":
            cursor.execute('DELETE FROM reviews WHERE id = ?', (review_id,))
            db_connection.commit()
            safe_send_message(admin_id, f"❌ Отзыв #{review_id} удален!")
        
        show_admin_reviews(admin_id)
    except Exception as e:
        logger.error(f"Ошибка в handle_review_action: {e}")

# Запуск бота
def start_bot():
    logger.info("🤖 MOLOCHNIY BOTIK запускается...")
    
    # Простой веб-сервер для хостинга
    try:
        from flask import Flask
        app = Flask(__name__)

        @app.route('/')
        def home():
            return "🤖 MOLOCHNIY BOTIK работает исправно! 🚀"

        @app.route('/health')
        def health():
            return "✅ OK"

        port = int(os.environ.get('PORT', 5000))
        threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False), daemon=True).start()
        logger.info(f"🌐 Веб-сервер запущен на порту {port}")
    except Exception as e:
        logger.error(f"⚠️ Веб-сервер не запущен: {e}")
    
    # Запуск бота
    while True:
        try:
            logger.info("✅ Бот успешно запущен и работает")
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            logger.error(f"❌ Ошибка в работе бота: {e}")
            logger.info("🔄 Перезапуск бота через 10 секунд...")
            time.sleep(10)

if __name__ == "__main__":
    start_bot()
