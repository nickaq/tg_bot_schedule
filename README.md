# NURE Moodle Attendance Bot

Telegram bot for automatically marking attendance in NURE's Moodle system (https://dl.nure.ua).

## Features

- Automated attendance marking for multiple users
- Smart attendance - marks only during scheduled class times
- Weekly schedule view with all classes
- Match attendance URLs with actual subjects in schedule
- Secure credential storage (encrypted)
- Multiple lesson tracking
- Regular checks (configurable interval)
- Telegram notifications when attendance is marked

## Commands

- `/start` - Start the bot and get help
- `/set_credentials` - Set your Moodle login and password
- `/add_lesson <url>` - Add a lesson to track
- `/list_lessons` - View all your tracked lessons
- `/remove_lesson` - Remove a lesson from tracking
- `/toggle_lesson` - Enable/disable automatic attendance for specific lessons
- `/cancel` - Cancel any ongoing operation

## Setup

1. Clone this repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Create a `.env` file in the project root with the following:
   ```
   TELEGRAM_TOKEN=your_telegram_bot_token
   ENCRYPTION_KEY=your_encryption_key
   DATABASE_URL=sqlite:///bot_database.db  # Or use PostgreSQL URL
   ```
4. Run the bot:
   ```
   python bot.py
   ```

## Creating a Telegram Bot

To get your TELEGRAM_TOKEN:
1. Talk to [@BotFather](https://t.me/BotFather) on Telegram
2. Use the `/newbot` command and follow instructions
3. Copy the API token provided by BotFather

## Project Structure

- `bot.py` - Main entry point
- `config.py` - Configuration and constants
- `db/` - Database models and connection handling
- `moodle/` - Moodle client for interacting with dl.nure.ua
- `scheduler/` - Scheduled tasks for attendance checking
- `telegram/` - Telegram bot handlers and logic

## Security

All Moodle passwords are encrypted using Fernet symmetric encryption from the Python `cryptography` library. The encryption key is stored in the `.env` file and should be kept private.

## Deployment

For production deployment, consider:
- Using a process manager like Supervisor
- Setting up a proper database (PostgreSQL)
- Using a hosting provider with persistent storage

## License

MIT
