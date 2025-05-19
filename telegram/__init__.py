"""Telegram bot module for NURE Moodle attendance bot."""
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from .handlers import register_handlers

# Initialize bot and dispatcher
bot = None
dispatcher = None

def init_bot(token: str):
    """Initialize the bot with the given token.
    
    Args:
        token: Telegram bot token
    """
    global bot, dispatcher
    
    bot = Bot(token=token)
    storage = MemoryStorage()
    dispatcher = Dispatcher(storage=storage)
    
    # Register all handlers
    register_handlers(dispatcher)
    
    return bot, dispatcher
