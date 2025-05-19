import logging
import asyncio
import sys
import os
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, BotCommandScopeDefault
from telegram.handlers import register_handlers
from scheduler.tasks import AttendanceScheduler
from config import TELEGRAM_TOKEN, ENCRYPTION_KEY

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


async def on_startup(bot, dispatcher):
    """Actions to perform on bot startup"""
    logger.info("Starting bot...")
    
    # Set up commands for Telegram menu button
    commands = [
        BotCommand(command="start", description="Запустити бота / інформація"),
        BotCommand(command="status", description="Перевірити статус авторизації та активні предмети"),
        BotCommand(command="set_credentials", description="Налаштувати облікові дані Moodle"),
        BotCommand(command="add_lesson", description="Додати заняття для відстеження"),
        BotCommand(command="list_lessons", description="Показати список занять"),
        BotCommand(command="remove_lesson", description="Видалити заняття"),
        BotCommand(command="toggle_lesson", description="Увімкнути/вимкнути заняття"),
        BotCommand(command="schedule", description="Показати розклад занять"),
        BotCommand(command="cancel", description="Скасувати поточну операцію")
    ]
    
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    logger.info("Bot commands menu has been configured")


async def on_shutdown(bot, dispatcher):
    """Actions to perform on bot shutdown"""
    logger.info("Shutting down bot...")
    
    # Close storage
    await dispatcher.storage.close()
    
    # Stop scheduler
    if hasattr(bot, 'scheduler'):
        bot.scheduler.stop()


async def main():
    """Main function to start the bot"""
    # Check if environment variables are set
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN is not set in the environment variables or .env file")
        return
    
    if not ENCRYPTION_KEY:
        logger.warning("ENCRYPTION_KEY is not set! A new random key will be generated.")
        logger.warning("This will make existing encrypted passwords unusable!")
        
        # Generate and save a new key
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        
        # Update .env file or create if it doesn't exist
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        env_content = f"ENCRYPTION_KEY={key}\n"
        
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                lines = f.readlines()
            
            key_set = False
            for i, line in enumerate(lines):
                if line.startswith("ENCRYPTION_KEY="):
                    lines[i] = f"ENCRYPTION_KEY={key}\n"
                    key_set = True
                    break
            
            if not key_set:
                lines.append(f"ENCRYPTION_KEY={key}\n")
            
            with open(env_path, 'w') as f:
                f.writelines(lines)
        else:
            with open(env_path, 'w') as f:
                f.write(env_content)
        
        logger.info("Generated and saved a new encryption key")
    
    # Initialize bot and dispatcher
    bot = Bot(token=TELEGRAM_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Register all handlers
    register_handlers(dp)
    
    # Initialize scheduler
    scheduler = AttendanceScheduler(bot)
    bot.scheduler = scheduler
    
    # Start scheduler
    scheduler.start()
    
    # Set up startup handler
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    try:
        # Удаляем webhook, если он был установлен
        logger.info("Удаление webhook и ожидание обновления статуса...")
        await bot.delete_webhook(drop_pending_updates=True)
        
        # Небольшая пауза, чтобы дать серверам Telegram время обновить статус
        logger.info("Ожидание 5 секунд для обновления статуса на серверах Telegram...")
        await asyncio.sleep(5)
        
        # Start polling with extended timeout
        logger.info("Запуск polling...")
        await dp.start_polling(bot, skip_updates=True, timeout=30, allowed_updates=['message', 'callback_query'])
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {str(e)}")
        
        # Попытка корректно закрыть все ресурсы
        try:
            await dp.storage.close()
            if hasattr(bot, 'scheduler'):
                bot.scheduler.stop()
            await bot.session.close()
        except Exception as close_error:
            logger.error(f"Ошибка при закрытии ресурсов: {str(close_error)}")
        
        # Повторно генерируем исключение
        raise


if __name__ == '__main__':
    asyncio.run(main())
