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


class LessonForm(StatesGroup):
    """States for adding a lesson"""
    url = State()
    name = State()


# Create bot and dispatcher
storage = MemoryStorage()


async def start_command(message: Message):
    """Handler for /start command"""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    session = get_db_session()
    try:
        # Check if user exists, create if not
        user = DatabaseManager.get_user_by_telegram_id(session, user_id)
        if not user:
            DatabaseManager.create_user(session, user_id)
            logger.info(f"Created new user: {user_id}")
        
        # Create keyboard with main commands
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🔑 Налаштувати облікові дані"), KeyboardButton(text="➕ Додати заняття")],
                [KeyboardButton(text="📋 Список занять"), KeyboardButton(text="❌ Видалити заняття")],
                [KeyboardButton(text="⚙️ Увімкнути/вимкнути заняття"), KeyboardButton(text="📊 Статус")],
            ],
            resize_keyboard=True,
            is_persistent=True
        )
        
        # Welcome message in Ukrainian
        await message.answer(
            f"👋 Вітаю, {username}!\n\n"
            f"Я бот, який може автоматично відмічати вашу присутність на заняттях у системі dl.nure.ua.\n\n"
            f"Щоб почати, налаштуйте свої облікові дані Moodle, натиснувши '🔑 Налаштувати облікові дані'.\n"
            f"Потім додайте свої заняття через '➕ Додати заняття'.\n\n"
            f"Доступні команди:\n"
            f"🔑 Налаштувати облікові дані - Встановити логін та пароль для Moodle\n"
            f"➕ Додати заняття - Додати заняття для відстеження відвідуваності\n"
            f"📋 Список занять - Показати збережені заняття\n"
            f"❌ Видалити заняття - Видалити збережене заняття\n"
            f"⚙️ Увімкнути/вимкнути заняття - Увімкнути/вимкнути автоматичну відмітку для занять\n"
            f"📊 Статус - Перевірити статус авторизації та активні предмети\n\n"
            f"Я автоматично перевірятиму ваші заняття кожні кілька хвилин і відмічатиму присутність, коли це можливо.",
            reply_markup=keyboard
        )
    finally:
        session.close()


async def set_credentials_command(message: Message, state: FSMContext):
    """Handler for /set_credentials command"""
    await message.answer(
        "Будь ласка, введіть вашу електронну адресу Moodle (логін):\n\n"
        "Це має бути електронна адреса, яку ви використовуєте для входу в dl.nure.ua"
    )
    await state.set_state(CredentialsForm.username)


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
            await message.answer(
                "✅ Ваші облікові дані Moodle успішно збережено!\n\n"
                "Тепер ви можете додати заняття, натиснувши '➕ Додати заняття'"
            )
        else:
            await message.answer(
                "❌ Не вдалося зберегти ваші облікові дані. Будь ласка, спробуйте пізніше."
            )
    finally:
        session.close()
    
    # Finish the state
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
    """Handler for /schedule command - shows today's and weekly class schedule from CSV file"""
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
        
        # Build the response message
        response_parts = []
        
        # 1. Current class status
        if is_class_time and current_class:
            subject = current_class.get('subject', 'Заняття')
            start_time = current_class['start_time'].strftime("%H:%M")
            end_time = current_class['end_time'].strftime("%H:%M")
            response_parts.append(f"✨ <b>Поточне заняття:</b> {subject} ({start_time} - {end_time})\n")
        else:
            response_parts.append("✨ <b>Зараз немає занять</b>\n")
        
        # Get weekly schedule in a compact format organized by weekday
        weekly_schedule = parser.get_weekly_schedule()
        response_parts.append(weekly_schedule)
        
        # Send the complete message
        await message.answer("\n".join(response_parts), parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Error in schedule command: {e}", exc_info=True)
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
        is_logged_in = bool(user.moodle_username and user.encrypted_password)
        
        # Get active lessons
        lessons = DatabaseManager.get_user_lessons(session, user_id, active_only=True)
        
        # Format status message
        status_text = "📊 Ваш поточний статус:\n\n"
        
        # Login status
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
    dp.message.register(schedule_command, F.text == "📅 Розклад занять")
    dp.message.register(cancel_command, Command(commands=["cancel"]))
    dp.message.register(cancel_command, F.text == "Скасувати")
    
    # Form state handlers
    dp.message.register(process_username, CredentialsForm.username)
    dp.message.register(process_password, CredentialsForm.password)
    dp.message.register(process_lesson_url, LessonForm.url)
    dp.message.register(process_lesson_name, LessonForm.name)
    
    # Callback query handlers
    dp.callback_query.register(remove_lesson_callback, F.data.startswith("remove_"))
    dp.callback_query.register(toggle_lesson_callback, F.data.startswith("toggle_"))
    
    return dp
