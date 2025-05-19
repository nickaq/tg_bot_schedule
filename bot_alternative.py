import logging
import asyncio
import sys
import os
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.session.aiohttp import AiohttpSession
from telegram.handlers import register_handlers
from scheduler.tasks import AttendanceScheduler
from config import TELEGRAM_TOKEN, ENCRYPTION_KEY

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_alt.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


async def on_startup(bot, dispatcher):
    """Actions to perform on bot startup"""
    logger.info("Starting alternative bot implementation...")
    
    # Set up commands for Telegram menu button
    commands = [
        types.BotCommand(command="start", description="Запустити бота / інформація"),
        types.BotCommand(command="set_credentials", description="Налаштувати облікові дані Moodle"),
        types.BotCommand(command="add_lesson", description="Додати заняття для відстеження"),
        types.BotCommand(command="list_lessons", description="Показати список занять"),
        types.BotCommand(command="remove_lesson", description="Видалити заняття"),
        types.BotCommand(command="toggle_lesson", description="Увімкнути/вимкнути заняття"),
        types.BotCommand(command="cancel", description="Скасувати поточну операцію")
    ]
    
    await bot.set_my_commands(commands, scope=types.BotCommandScopeDefault())
    logger.info("Bot commands menu has been configured")


async def on_shutdown(bot, dispatcher):
    """Actions to perform on bot shutdown"""
    logger.info("Shutting down bot...")
    
    # Close storage
    await dispatcher.storage.close()
    
    # Stop scheduler
    if hasattr(bot, 'scheduler'):
        bot.scheduler.stop()
    
    # Close bot session
    await bot.session.close()


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
    
    # Initialize custom session
    session = AiohttpSession()
    
    # Initialize bot and dispatcher with custom session
    bot = Bot(token=TELEGRAM_TOKEN, session=session)
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
    
    # First, delete webhook to clear any previous conflicts
    logger.info("Removing webhook and cleaning up previous sessions...")
    await bot.delete_webhook(drop_pending_updates=True)
    
    try:
        # Start polling with more aggressive configuration
        logger.info("Starting polling with alternative configuration...")
        await dp.start_polling(
            bot, 
            skip_updates=True, 
            timeout=60,  # Longer timeout
            allowed_updates=['message', 'callback_query'],
            polling_timeout=60  # Longer polling timeout
        )
    except Exception as e:
        logger.error(f"Error in polling: {str(e)}")
        await bot.session.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user or system")
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
