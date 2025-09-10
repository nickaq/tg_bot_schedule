import re
import logging
import os.path
from aiogram import Bot, Dispatcher, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.markdown import hbold, hitalic
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from db.models import get_db_session
from db.database import DatabaseManager
from config import MOODLE_BASE_URL
from simple_schedule_parser import SimpleScheduleParser
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Define states for conversation handlers
class CredentialsForm(StatesGroup):
    """States for credentials form"""
    username = State()
    password = State()


class GroupForm(StatesGroup):
    """States for group selection"""
    group = State()


class LessonForm(StatesGroup):
    """States for adding a lesson"""
    url = State()
    name = State()


# Create bot and dispatcher
storage = MemoryStorage()


async def start_command(message: Message, state: FSMContext):
    """Handler for /start command"""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    session = get_db_session()
    try:
        # Check if user exists, create if not
        user = DatabaseManager.get_user_by_telegram_id(session, user_id)
        if not user:
            user = DatabaseManager.create_user(session, user_id)
            logger.info(f"Created new user: {user_id}")
        
        # Create keyboard with main commands
        main_keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🔑 Налаштувати облікові дані"), KeyboardButton(text="➕ Додати заняття")],
                [KeyboardButton(text="📋 Список занять"), KeyboardButton(text="❌ Видалити заняття")],
                [KeyboardButton(text="⚙️ Увімкнути/вимкнути заняття"), KeyboardButton(text="📊 Статус")],
                [KeyboardButton(text="📆 Сьогодні"), KeyboardButton(text="📅 Тиждень")],
                [KeyboardButton(text="🔍 Поточне заняття"), KeyboardButton(text="📋 Повний розклад")],
            ],
            resize_keyboard=True,
            is_persistent=True
        )
        
        # If user doesn't have credentials yet
        if not user.moodle_username or not user.encrypted_password:
            await message.answer(
                f"👋 Вітаю, {username}!\n\n"
                f"Я бот, який може автоматично відмічати вашу присутність на заняттях у системі dl.nure.ua.\n\n"
                f"Щоб почати, налаштуйте свої облікові дані Moodle, натиснувши '🔑 Налаштувати облікові дані'.",
                reply_markup=main_keyboard
            )
        # If user has credentials but no group selected
        elif not user.group:
            # Create group selection keyboard
            group_keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="ІТШІ")],
                    [KeyboardButton(text="КНТ")],
                    [KeyboardButton(text="ІТУ")],
                ],
                resize_keyboard=True,
                one_time_keyboard=True
            )
            
            await message.answer(
                f"👋 Вітаю, {username}!\n\n"
                f"Для правильної роботи бота, будь ласка, оберіть вашу групу:",
                reply_markup=group_keyboard
            )
            
            # Set state to wait for group selection
            await state.set_state(GroupForm.group)
        # User has both credentials and group
        else:
            await message.answer(
                f"👋 Вітаю, {username}!\n\n"
                f"Ваша група: {user.group}\n\n"
                f"Доступні команди:\n"
                f"🔑 Налаштувати облікові дані - Встановити логін та пароль для Moodle\n"
                f"➕ Додати заняття - Додати заняття для відстеження відвідуваності\n"
                f"📊 Статус - Перевірити статус авторизації та активні предмети\n\n"
                f"Я автоматично перевірятиму ваші заняття кожні 30 хвилин і відмічатиму присутність, коли це можливо.",
                reply_markup=main_keyboard
            )
    finally:
        session.close()


async def set_credentials_command(message: Message, state: FSMContext):
    """Handler for /set_credentials command"""
    # Get user's current active status
    session = get_db_session()
    user_id = message.from_user.id
    active_status = True  # Default to active
    
    try:
        user = DatabaseManager.get_user_by_telegram_id(session, user_id)
        if user:
            active_status = user.active
    finally:
        session.close()
    
    # Create settings menu with options
    status_text = "✅ Активний" if active_status else "❌ Неактивний"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Налаштувати логін/пароль", callback_data="settings:credentials")],
        [InlineKeyboardButton(text="👥 Змінити групу", callback_data="settings:group")],
        [InlineKeyboardButton(text=f"🔄 Перемкнути статус бота ({status_text})", callback_data="settings:toggle_active")]
    ])
    
    await message.answer(
        "⚙️ Налаштування облікового запису:\n\n"
        "Оберіть, що ви хочете налаштувати:",
        reply_markup=keyboard
    )


async def handle_settings_callback(callback: CallbackQuery, state: FSMContext):
    """Handler for settings callback queries"""
    await callback.answer()
    
    # Get the settings action
    action = callback.data.split(':')[1]
    user_id = callback.from_user.id
    
    if action == "credentials":
        await callback.message.answer(
            "Будь ласка, введіть вашу електронну адресу Moodle (логін):\n\n"
            "Це має бути електронна адреса, яку ви використовуєте для входу в dl.nure.ua"
        )
        await state.set_state(CredentialsForm.username)
    elif action == "group":
        # Create group selection keyboard
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="ІТШІ")],
                [KeyboardButton(text="КНТ")],
                [KeyboardButton(text="ІТУ")],
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        await callback.message.answer(
            "👥 Будь ласка, оберіть вашу групу:",
            reply_markup=keyboard
        )
        await state.set_state(GroupForm.group)
    elif action == "toggle_active":
        session = get_db_session()
        try:
            # Toggle user active status
            success, new_status = DatabaseManager.toggle_user_active_status(session, user_id)
            
            if success:
                status_text = "активний" if new_status else "неактивний"
                await callback.message.edit_text(
                    f"⚙️ Статус бота успішно змінено!\n\n"
                    f"Тепер бот {status_text}. "
                    f"{'\n\nБот буде автоматично перевіряти відвідуваність.' if new_status else '\n\nБот не буде перевіряти відвідуваність поки ви не активуєте його.'}"
                )
            else:
                await callback.message.answer(
                    "❌ Помилка при зміні статусу бота. Будь ласка, спробуйте пізніше."
                )
        finally:
            session.close()


async def process_username(message: Message, state: FSMContext):
    """Process username and ask for password"""
    email = message.text.strip()
    
    # Basic email validation
    if '@' not in email or '.' not in email:
        await message.answer(
            "❌ Це не схоже на дійсну електронну адресу. Будь ласка, введіть електронну адресу, яку ви використовуєте для входу в dl.nure.ua."
        )
        return
    
    # Save email as username
    await state.update_data(username=email)
    
    # Ask for password
    await message.answer(
        "Тепер, будь ласка, введіть ваш пароль для Moodle:\n\n"
        "⚠️ Примітка: Ваш пароль буде зашифровано для безпеки, але майте на увазі, що ви передаєте його цьому боту. Він буде використаний тільки для входу в Moodle."
    )
    await state.set_state(CredentialsForm.password)


async def process_password(message: Message, state: FSMContext):
    """Process password and save credentials"""
    user_data = await state.get_data()
    username = user_data.get('username')
    password = message.text
    user_id = message.from_user.id
    
    # Delete the message with password for security
    await message.delete()
    
    session = get_db_session()
    try:
        # Save credentials
        user = DatabaseManager.set_user_credentials(session, user_id, username, password)
        
        if user:
            # Create group selection keyboard
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="ІТШІ")],
                    [KeyboardButton(text="КНТ")],
                    [KeyboardButton(text="ІТУ")],
                ],
                resize_keyboard=True,
                one_time_keyboard=True
            )
            
            await message.answer(
                "✅ Ваші облікові дані Moodle успішно збережено!\n\n"
                "Будь ласка, оберіть вашу групу:",
                reply_markup=keyboard
            )
            await state.set_state(GroupForm.group)
            return
        else:
            await message.answer(
                "❌ Не вдалося зберегти ваші облікові дані. Будь ласка, спробуйте пізніше."
            )
    finally:
        session.close()
    
    # Finish the state if something went wrong
    await state.clear()


async def add_lesson_command(message: Message, state: FSMContext):
    """Handler for /add_lesson command"""
    user_id = message.from_user.id
    
    session = get_db_session()
    try:
        user = DatabaseManager.get_user_by_telegram_id(session, user_id)
        if not user or not user.moodle_username or not user.encrypted_password:
            await message.answer(
                "❌ Ви ще не налаштували свої облікові дані Moodle.\n"
                "Спочатку скористайтесь кнопкою '🔑 Налаштувати облікові дані'."
            )
            return
        
        await message.answer(
            "Будь ласка, введіть URL-адресу сторінки заняття з dl.nure.ua. "
            "Вона має виглядати приблизно так: https://dl.nure.ua/mod/attendance/view.php?id=123456"
        )
        await state.set_state(LessonForm.url)
    finally:
        session.close()


async def process_group(message: Message, state: FSMContext):
    """Process group selection"""
    group = message.text.strip()
    user_id = message.from_user.id
    
    # Validate group
    valid_groups = ["ІТШІ", "КНТ", "ІТУ"]
    if group not in valid_groups:
        await message.answer(
            "❌ Будь ласка, оберіть групу зі списку, використовуючи кнопки."
        )
        return
    
    session = get_db_session()
    try:
        # Save group
        success = DatabaseManager.set_user_group(session, user_id, group)
        
        if success:
            # Create keyboard with main commands
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="🔑 Налаштувати облікові дані")],
                    [KeyboardButton(text="➕ Додати заняття"), KeyboardButton(text="❌ Видалити заняття")],
                    [KeyboardButton(text="📋 Список занять"), KeyboardButton(text="⚙️ Увімкнути/вимкнути заняття")],
                    [KeyboardButton(text="📊 Статус")]
                ],
                resize_keyboard=True
            )
            
            await message.answer(
                f"✅ Ваша група успішно збережена: {group}\n\n"
                f"Тепер ви можете додати заняття, натиснувши '➕ Додати заняття'",
                reply_markup=keyboard
            )
        else:
            await message.answer(
                "❌ Не вдалося зберегти групу. Будь ласка, спробуйте пізніше."
            )
    finally:
        session.close()
    
    # Finish the state
    await state.clear()


async def process_lesson_url(message: Message, state: FSMContext):
    """Process lesson URL and ask for name"""
    url = message.text.strip()
    
    # Validate URL
    if not url.startswith("https://dl.nure.ua/") and not url.startswith("http://dl.nure.ua/"):
        await message.answer(
            "❌ Невірний URL. Він має бути з домену dl.nure.ua.\n"
            "Спробуйте ще раз або напишіть 'Скасувати' для відміни"
        )
        return
    
    # Check for view.php
    if "view.php" not in url:
        await message.answer(
            "⚠️ URL не схожий на сторінку заняття.\n"
            "Переконайтеся, що він містить 'view.php?id=...' або подібне.\n"
            "Продовжити все одно? Напишіть 'Скасувати' якщо ні."
        )
    
    # Save URL
    await state.update_data(url=url)
    
    # Ask for lesson name
    await message.answer(
        "Будь ласка, введіть назву для цього заняття (наприклад, 'Математика 101' або 'Лаб. з програмування'):\n"
        "Ця назва буде використана в повідомленнях."
    )
    await state.set_state(LessonForm.name)


async def process_lesson_name(message: Message, state: FSMContext):
    """Process lesson name and save lesson"""
    user_data = await state.get_data()
    url = user_data.get('url')
    name = message.text.strip()
    user_id = message.from_user.id
    
    session = get_db_session()
    try:
        # Save lesson
        lesson = DatabaseManager.add_lesson(session, user_id, url, name)
        
        if lesson:
            await message.answer(
                f"✅ Заняття '{name}' успішно додано!\n\n"
                f"Я тепер буду автоматично перевіряти можливість відмітитись на цьому занятті.\n"
                f"Ви можете переглянути свої заняття, натиснувши '📋 Список занять'"
            )
        else:
            await message.answer(
                "❌ Не вдалось додати заняття. Будь ласка, спробуйте пізніше."
            )
    finally:
        session.close()
    
    # Finish the state
    await state.clear()


async def list_lessons_command(message: Message):
    """Handler for /list_lessons command"""
    user_id = message.from_user.id
    
    session = get_db_session()
    try:
        lessons = DatabaseManager.get_user_lessons(session, user_id)
        
        if not lessons:
            await message.answer(
                "Ви ще не додали жодного заняття.\n"
                "Використовуйте '➕ Додати заняття' щоб додати ваше перше заняття."
            )
            return
        
        # Prepare response message
        response = "Ваші збережені заняття:\n\n"
        
        for lesson in lessons:
            # Status indicator
            status = "✅ Активне" if lesson.active else "❌ Неактивне"
            
            # Last check and mark info
            last_check = "Ніколи" if not lesson.last_checked else lesson.last_checked.strftime("%d.%m.%Y %H:%M")
            last_mark = "Ніколи" if not lesson.last_marked else lesson.last_marked.strftime("%d.%m.%Y %H:%M")
            
            response += (
                f"ID: {lesson.id} - {lesson.name}\n"
                f"Статус: {status}\n"
                f"Остання перевірка: {last_check}\n"
                f"Остання відмітка: {last_mark}\n"
                f"URL: {lesson.url}\n\n"
            )
        
        response += (
            "Щоб видалити заняття, натисніть '❌ Видалити заняття'\n"
            "Щоб увімкнути/вимкнути статус активності, натисніть '⚙️ Увімкнути/вимкнути заняття'"
        )
        
        await message.answer(response)
    finally:
        session.close()


async def remove_lesson_command(message: Message):
    """Handler for /remove_lesson command"""
    user_id = message.from_user.id
    
    session = get_db_session()
    try:
        lessons = DatabaseManager.get_user_lessons(session, user_id)
        
        if not lessons:
            await message.answer(
                "Ви ще не додали жодного заняття.\n"
                "Використайте '➕ Додати заняття' щоб додати ваше перше заняття."
            )
            return
        
        # Create inline keyboard with lessons
        builder = InlineKeyboardMarkup(inline_keyboard=[])
        buttons = []
        for lesson in lessons:
            button_text = f"{lesson.name} (ID: {lesson.id})"
            callback_data = f"remove_{lesson.id}"
            buttons.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
        
        builder = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await message.answer(
            "Виберіть заняття для видалення:",
            reply_markup=builder
        )
    finally:
        session.close()


async def toggle_lesson_command(message: Message):
    """Handler for /toggle_lesson command"""
    user_id = message.from_user.id
    
    session = get_db_session()
    try:
        lessons = DatabaseManager.get_user_lessons(session, user_id)
        
        if not lessons:
            await message.answer(
                "Ви ще не додали жодного заняття.\n"
                "Використайте '➕ Додати заняття' щоб додати ваше перше заняття."
            )
            return
        
        # Create inline keyboard with lessons
        buttons = []
        for lesson in lessons:
            status = "✅" if lesson.active else "❌"
            button_text = f"{status} {lesson.name} (ID: {lesson.id})"
            callback_data = f"toggle_{lesson.id}"
            buttons.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
        
        builder = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await message.answer(
            "Виберіть заняття для увімкнення/вимкнення автоматичної відмітки:",
            reply_markup=builder
        )
    finally:
        session.close()


async def remove_lesson_callback(callback_query: CallbackQuery):
    """Handle remove lesson callback"""
    await callback_query.answer()
    
    # Extract lesson ID from callback data
    match = re.search(r'remove_(\d+)', callback_query.data)
    if not match:
        await callback_query.message.answer("Невірний вибір.")
        return
    
    lesson_id = int(match.group(1))
    user_id = callback_query.from_user.id
    
    session = get_db_session()
    try:
        # Remove lesson
        success = DatabaseManager.remove_lesson(session, user_id, lesson_id)
        
        if success:
            await callback_query.message.edit_text(
                f"✅ Заняття (ID: {lesson_id}) було успішно видалено."
            )
        else:
            await callback_query.message.answer(
                "❌ Не вдалося видалити заняття. Будь ласка, спробуйте пізніше."
            )
    finally:
        session.close()


async def toggle_lesson_callback(callback_query: CallbackQuery):
    """Handle toggle lesson callback"""
    await callback_query.answer()
    
    # Extract lesson ID from callback data
    match = re.search(r'toggle_(\d+)', callback_query.data)
    if not match:
        await callback_query.message.answer("Невірний вибір.")
        return
    
    lesson_id = int(match.group(1))
    user_id = callback_query.from_user.id
    
    session = get_db_session()
    try:
        # Toggle lesson status
        lesson = DatabaseManager.toggle_lesson_status(session, user_id, lesson_id)
        
        if lesson:
            status = "увімкнено" if lesson.active else "вимкнено"
            await callback_query.message.edit_text(
                f"✅ Заняття '{lesson.name}' (ID: {lesson_id}) було {status}."
            )
        else:
            await callback_query.message.answer(
                "❌ Не вдалося змінити статус заняття. Будь ласка, спробуйте пізніше."
            )
    finally:
        session.close()


async def cancel_command(message: Message, state: FSMContext):
    """Handler for /cancel command or 'Скасувати' text - cancels any ongoing form"""
    # Check if the message is 'Скасувати'
    if message.text.strip() == 'Скасувати':
        await message.answer("Дію скасовано. Оберіть інший пункт меню.")
    else:
        await message.answer("Поточну дію скасовано.")
    
    # Reset state
    await state.clear()


async def schedule_command(message: Message):
    """Handler for /schedule command - shows menu with schedule options"""
    try:
        # Create an inline keyboard with schedule options
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📆 Розклад на сьогодні", callback_data="schedule:today")],
            [InlineKeyboardButton(text="📅 Розклад на тиждень", callback_data="schedule:week")],
            [InlineKeyboardButton(text="🔍 Поточне заняття", callback_data="schedule:current")],
            [InlineKeyboardButton(text="📋 Повний розклад", callback_data="schedule:full")]
        ])
        
        # Send menu message
        await message.answer(
            "📚 Оберіть тип розкладу занять:", 
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Error in schedule command: {e}", exc_info=True)
        await message.answer("❌ Помилка при створенні меню розкладу. Спробуйте пізніше.")


async def handle_schedule_callback(callback: CallbackQuery):
    """Handler for schedule callback queries"""
    try:
        # Remove the 'schedule:' prefix from the callback data
        schedule_type = callback.data.split(':')[1]
        
        # Initialize schedule parser
        schedule_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                   'TimeTable.csv')
        parser = SimpleScheduleParser(schedule_path)
        
        if not parser.load_schedule():
            await callback.answer("Не вдалося завантажити розклад занять")
            await callback.message.answer("❌ Не вдалося завантажити розклад занять. Спробуйте пізніше.")
            return
        
        # Handle different schedule types
        response = ""
        
        if schedule_type == "today":
            # Today's schedule
            today_classes = parser.get_upcoming_classes(days=1)
            if today_classes:
                response = parser.format_schedule(today_classes)
            else:
                response = "📆 Сьогодні занять немає"
                
        elif schedule_type == "week":
            # Weekly schedule
            response = parser.get_weekly_schedule()
            
        elif schedule_type == "current":
            # Current class information
            is_class_time, current_class = parser.is_class_time()
            
            if is_class_time and current_class:
                subject = current_class.get('subject', 'Заняття')
                start_time = current_class['start_time'].strftime("%H:%M")
                end_time = current_class['end_time'].strftime("%H:%M")
                response = f"✨ <b>Поточне заняття:</b>\n\n📚 Предмет: {subject}\n🕒 Час: {start_time} - {end_time}"
            else:
                response = "✨ <b>Зараз немає занять</b>"
                
        elif schedule_type == "full":
            # Full schedule (all classes)
            all_classes = parser.schedule
            response = parser.format_schedule(all_classes)
            
        # Answer the callback to stop the loading animation
        await callback.answer()
        
        # Send the schedule
        await callback.message.answer(response, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Error in handle_schedule_callback: {e}", exc_info=True)
        await callback.answer("Помилка при отриманні розкладу")
        await callback.message.answer("❌ Помилка при отриманні розкладу. Спробуйте пізніше.")


async def today_schedule_command(message: Message):
    """Handler for "Розклад на сьогодні" button"""
    try:
        # Initialize schedule parser
        schedule_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                   'TimeTable.csv')
        parser = SimpleScheduleParser(schedule_path)
        
        if not parser.load_schedule():
            await message.answer("❌ Не вдалося завантажити розклад занять. Спробуйте пізніше.")
            return
            
        # Get today's classes
        today_classes = parser.get_upcoming_classes(days=1)
        if today_classes:
            response = parser.format_schedule(today_classes)
        else:
            response = "📆 Сьогодні занять немає"
        
        # Send the schedule
        await message.answer(response, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Error in today_schedule_command: {e}", exc_info=True)
        await message.answer("❌ Помилка при отриманні розкладу. Спробуйте пізніше.")


async def week_schedule_command(message: Message):
    """Handler for "Розклад на тиждень" button"""
    try:
        # Initialize schedule parser
        schedule_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                   'TimeTable.csv')
        parser = SimpleScheduleParser(schedule_path)
        
        if not parser.load_schedule():
            await message.answer("❌ Не вдалося завантажити розклад занять. Спробуйте пізніше.")
            return
            
        # Get weekly schedule
        response = parser.get_weekly_schedule()
        
        # Send the schedule
        await message.answer(response, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Error in week_schedule_command: {e}", exc_info=True)
        await message.answer("❌ Помилка при отриманні розкладу. Спробуйте пізніше.")


async def current_class_command(message: Message):
    """Handler for "Поточне заняття" button"""
    try:
        # Initialize schedule parser
        schedule_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                   'TimeTable.csv')
        parser = SimpleScheduleParser(schedule_path)
        
        if not parser.load_schedule():
            await message.answer("❌ Не вдалося завантажити розклад занять. Спробуйте пізніше.")
            return
            
        # Check if there's a class in session now
        is_class_time, current_class = parser.is_class_time()
        
        if is_class_time and current_class:
            subject = current_class.get('subject', 'Заняття')
            start_time = current_class['start_time'].strftime("%H:%M")
            end_time = current_class['end_time'].strftime("%H:%M")
            response = f"✨ <b>Поточне заняття:</b>\n\n📚 Предмет: {subject}\n🕒 Час: {start_time} - {end_time}"
        else:
            response = "✨ <b>Зараз немає занять</b>"
        
        # Send the current class info
        await message.answer(response, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Error in current_class_command: {e}", exc_info=True)
        await message.answer("❌ Помилка при отриманні інформації про заняття. Спробуйте пізніше.")


async def full_schedule_command(message: Message):
    """Handler for "Повний розклад" button"""
    try:
        # Initialize schedule parser
        schedule_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                   'TimeTable.csv')
        parser = SimpleScheduleParser(schedule_path)
        
        if not parser.load_schedule():
            await message.answer("❌ Не вдалося завантажити розклад занять. Спробуйте пізніше.")
            return
            
        # Get full schedule
        all_classes = parser.schedule
        response = parser.format_schedule(all_classes)
        
        # Send the full schedule
        await message.answer(response, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Error in full_schedule_command: {e}", exc_info=True)
        await message.answer("❌ Помилка при отриманні розкладу. Спробуйте пізніше.")


async def status_command(message: Message):
    """Handler for /status command - shows login status and active lessons"""
    user_id = message.from_user.id
    
    session = get_db_session()
    try:
        # Check if user exists and has credentials
        user = DatabaseManager.get_user_by_telegram_id(session, user_id)
        
        if not user:
            await message.answer("❌ Ви ще не зареєстровані в системі. Використайте команду /start для початку роботи.")
            return
        
        # Check if user has Moodle credentials
        if not user.moodle_username or not user.encrypted_password:
            await message.answer(
                "❌ Ви ще не налаштували свої облікові дані Moodle.\n"
                "Використайте '🔑 Налаштувати облікові дані' для налаштування."
            )
            return
            
        # Get all lessons for the user
        lessons = DatabaseManager.get_user_lessons(session, user_id)
        
        # Prepare status message
        status_text = f"<b>📊 Статус облікового запису:</b>\n\n"
        status_text += f"🔑 Логін: {user.moodle_username}\n"
        status_text += f"👥 Група: {user.group or 'Не вибрана'}\n"
        status_text += f"🔄 Статус бота: {'Активний' if user.active else 'Неактивний'}\n\n"
        
        # Login status
        is_logged_in = bool(user.moodle_username and user.encrypted_password)
        
        if is_logged_in:
            status_text += f"✅ {hbold('Статус авторизації:')} Ви авторизовані в системі dl.nure.ua як {hitalic(user.moodle_username)}\n\n"
        else:
            status_text += f"❌ {hbold('Статус авторизації:')} Ви не авторизовані в системі dl.nure.ua\n"
            status_text += "Використайте '🔑 Налаштувати облікові дані' для налаштування\n\n"
        
        # Lessons
        status_text += f"{hbold('Предмети для автоматичної відмітки:')}\n"
        
        if lessons:
            for i, lesson in enumerate(lessons, 1):
                lesson_name = lesson.name or "Без назви"
                status_text += f"{i}. {hbold(lesson_name)}\n"
                # Add last checked and marked info if available
                if lesson.last_checked:
                    last_checked = lesson.last_checked.strftime("%d.%m.%Y %H:%M")
                    status_text += f"   Остання перевірка: {last_checked}\n"
                if lesson.last_marked:
                    last_marked = lesson.last_marked.strftime("%d.%m.%Y %H:%M")
                    status_text += f"   Остання відмітка: {last_marked}\n"
        else:
            status_text += "У вас немає активних предметів для відмітки.\n"
            status_text += "Використайте '➕ Додати заняття' для додавання предметів.\n"
        
        await message.answer(status_text, parse_mode="HTML")
    finally:
        session.close()


def register_handlers(dp: Dispatcher):
    """Register all handlers with the dispatcher"""
    # Command handlers
    dp.message.register(start_command, Command(commands=["start"]))
    dp.message.register(set_credentials_command, Command(commands=["set_credentials"]))
    dp.message.register(set_credentials_command, F.text == "🔑 Налаштувати облікові дані")
    dp.message.register(add_lesson_command, Command(commands=["add_lesson"]))
    dp.message.register(add_lesson_command, F.text == "➕ Додати заняття")
    dp.message.register(list_lessons_command, Command(commands=["list_lessons"]))
    dp.message.register(list_lessons_command, F.text == "📋 Список занять")
    dp.message.register(remove_lesson_command, Command(commands=["remove_lesson"]))
    dp.message.register(remove_lesson_command, F.text == "❌ Видалити заняття")
    dp.message.register(toggle_lesson_command, Command(commands=["toggle_lesson"]))
    dp.message.register(toggle_lesson_command, F.text == "⚙️ Увімкнути/вимкнути заняття")
    dp.message.register(status_command, Command(commands=["status"]))
    dp.message.register(status_command, F.text == "📊 Статус")
    dp.message.register(schedule_command, Command(commands=["schedule"]))
    
    # Register schedule button handlers
    dp.message.register(today_schedule_command, F.text == "📆 Сьогодні")
    dp.message.register(week_schedule_command, F.text == "📅 Тиждень")
    dp.message.register(current_class_command, F.text == "🔍 Поточне заняття")
    dp.message.register(full_schedule_command, F.text == "📋 Повний розклад")
    
    dp.message.register(cancel_command, Command(commands=["cancel"]))
    dp.message.register(cancel_command, F.text == "Скасувати")
    
    # Form state handlers
    dp.message.register(process_username, CredentialsForm.username)
    dp.message.register(process_password, CredentialsForm.password)
    dp.message.register(process_group, GroupForm.group)
    dp.message.register(process_lesson_url, LessonForm.url)
    dp.message.register(process_lesson_name, LessonForm.name)
    
    # Callback query handlers
    dp.callback_query.register(remove_lesson_callback, F.data.startswith("remove_"))
    dp.callback_query.register(toggle_lesson_callback, F.data.startswith("toggle_"))
    dp.callback_query.register(handle_schedule_callback, F.data.startswith("schedule:"))
    dp.callback_query.register(handle_settings_callback, F.data.startswith("settings:"))
    
    return dp
