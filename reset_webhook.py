import asyncio
import logging
from aiogram import Bot
from config import TELEGRAM_TOKEN

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def reset_webhook():
    """Reset webhook and clear pending updates"""
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN is not set")
        return
    
    bot = Bot(token=TELEGRAM_TOKEN)
    
    # Delete webhook
    logger.info("Deleting webhook...")
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Get bot info
    bot_info = await bot.get_me()
    logger.info(f"Connected to bot: {bot_info.username} (ID: {bot_info.id})")
    
    # Close session
    await bot.session.close()
    logger.info("Bot session closed")
    
    return True

if __name__ == "__main__":
    try:
        result = asyncio.run(reset_webhook())
        if result:
            logger.info("Webhook reset complete. You can now run the bot.")
        else:
            logger.error("Failed to reset webhook.")
    except Exception as e:
        logger.error(f"Error: {str(e)}")
