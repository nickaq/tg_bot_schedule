import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Telegram Bot configuration
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')

# Database configuration
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///bot_database.db')

# Moodle configuration
MOODLE_BASE_URL = 'https://dl.nure.ua'
LOGIN_URL = f'{MOODLE_BASE_URL}/login/index.php'
ATTENDANCE_CHECK_INTERVAL = 5  # minutes

# Encryption settings
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')

# Scheduler settings
CHECK_INTERVAL_MINUTES = 7  # Check every 7 minutes for attendance opportunities
