import logging
import datetime
import pytz
import asyncio
from typing import Dict, List, Optional, Tuple
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from db.models import get_db_session, User
from db.database import DatabaseManager
from moodle.client import MoodleClient
from simple_schedule_parser import SimpleScheduleParser
from config import CHECK_INTERVAL_MINUTES
import os.path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AttendanceScheduler:
    """Scheduler for periodic attendance checks"""
    
    def __init__(self, bot=None):
        """Initialize the scheduler"""
        self.scheduler = BackgroundScheduler(timezone=pytz.timezone('Europe/Kiev'))
        self.bot = bot  # Telegram bot instance for sending notifications
        
        # Initialize the schedule parser
        schedule_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                    'TimeTable.csv')
        self.schedule_parser = SimpleScheduleParser(schedule_path)
    
    def start(self):
        """Start the scheduler"""
        # Check all attendance links every 5 minutes
        self.scheduler.add_job(
            self._run_check_attendance, 
            'interval', 
            minutes=5,
            next_run_time=datetime.datetime.now(pytz.UTC) + datetime.timedelta(seconds=10)  # Start first check after 10 seconds
        )
        
        self.scheduler.start()
        
        # Load the schedule data
        self.schedule_parser.load_schedule()
        
        logger.info(f"Scheduler started. Checking all attendance links every 5 minutes")
        
    def reload_schedule(self):
        """Reload the schedule from CSV file"""
        logger.info("Reloading schedule from CSV file")
        try:
            result = self.schedule_parser.load_schedule()
            if result:
                logger.info("Successfully reloaded schedule")
            else:
                logger.error("Failed to reload schedule")
            return result
        except Exception as e:
            logger.error(f"Error reloading schedule: {e}")
            return False
    
    def _run_check_attendance(self):
        """Non-async wrapper for async attendance check to be used with scheduler"""
        try:
            # Create a new event loop for current thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Run async check in this thread
            loop.run_until_complete(self._run_check_attendance_async())
            
            # Close event loop
            loop.close()
        except Exception as e:
            logger.error(f"Error scheduling attendance check: {e}")
    
    def check_is_class_time(self, current_time=None):
        """Check if it's currently class time based on the CSV schedule.
        
        Args:
            current_time: Current datetime (optional, defaults to now)
            
        Returns:
            Tuple:
              - bool: True if it's currently class time, False otherwise
              - dict: Information about the current class if it's class time, None otherwise
        """
        try:
            return self.schedule_parser.is_class_time(current_time)
        except Exception as e:
            logger.error(f"Error checking class time: {e}")
            return True, None  # In case of error, return True (assume it's class time)
        
    def stop(self):
        """Stop the scheduler"""
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")
            
    async def _run_check_attendance_async(self):
        """Run the attendance check for all users"""
        logger.info("Starting attendance check for all users")
        
        try:
            session = get_db_session()
            try:
                # Get all active users with their lessons
                user_lessons = DatabaseManager.get_all_active_users_and_lessons(session)
                # Extract users
                users = [user for user, _ in user_lessons] if user_lessons else []
                
                if not users:
                    logger.info("No users found for attendance check")
                    return
                
                # Check attendance for all users
                await self.check_all_attendances()
                    
            except Exception as e:
                logger.error(f"Error in attendance check: {str(e)}")
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Error in attendance check: {str(e)}")
    
    async def check_all_attendances(self):
        """Check attendance for all active users and lessons"""
        logger.info("Starting attendance check for all users")
        
        session = get_db_session()
        try:
            # Get all active users with their lessons
            user_lessons = DatabaseManager.get_all_active_users_and_lessons(session)
            # Extract users
            users = [user for user, _ in user_lessons] if user_lessons else []
            
            for user in users:
                try:
                    # Skip if user has no credentials or is inactive
                    if not user.moodle_username or not user.encrypted_password or not user.active:
                        continue
                        
                    # Get all lessons for this user, regardless of status
                    all_lessons = DatabaseManager.get_user_lessons(session, user.id)
                    
                    # Check attendance for all lessons
                    await self.check_user_attendances(user, all_lessons)
                    
                except Exception as e:
                    logger.error(f"Error checking attendance for user {user.telegram_id}: {str(e)}")
        
        except Exception as e:
            logger.error(f"Error in attendance check: {str(e)}")
        finally:
            session.close()
    
    async def check_user_attendances(self, user, lessons):
        """Check and mark attendance for a user's lessons"""
        logger.info(f"Checking attendance for user {user.telegram_id}, {len(lessons)} lessons")
        
        try:
            # Skip processing if no lessons found
            if not lessons:
                logger.info(f"No lessons found for user {user.telegram_id}")
                return
            
            # Get Moodle client for this user
            client = MoodleClient(user.moodle_username, user.moodle_password)
            
            # Process all lessons without filtering by current class or subject
            for lesson in lessons:
                # Skip inactive lessons
                if not lesson.active:
                    continue
                
                # Check attendance for this lesson
                await self.check_lesson_attendance(user, lesson, client)
                
                # Add a small delay between requests to avoid rate limiting
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"Error processing lessons for user {user.telegram_id}: {e}")
                
    # Helper method for sending notifications
    async def send_notification(self, chat_id, text):
        if self.bot:
            await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                disable_notification=True
            )
    
    async def check_lesson_attendance(self, user, lesson, client):
        """Check and mark attendance for a specific lesson"""
        logger.info(f"Checking attendance for user {user.telegram_id}, lesson {lesson.id}")
        
        session = get_db_session()
        try:
            # Update last check time
            DatabaseManager.update_lesson_check_time(session, lesson.id)
            
            # Check if attendance is available
            check_result = client.check_attendance(lesson.url)
            
            if check_result['status'] == 'available':
                # Attendance is available, mark it
                result = client.mark_attendance(lesson.url)
                
                if result['status'] == 'success':
                    # Update last marked time
                    DatabaseManager.update_lesson_mark_time(session, lesson.id)
                    
                    # Notify user about successful marking
                    if self.bot:
                        import asyncio
                        lesson_name = lesson.name or f"Заняття #{lesson.id}"
                        try:
                            asyncio.create_task(self.send_notification(
                                user.telegram_id,
                                f"✅ Успішно відмічено присутність на {lesson_name}!"
                            ))
                        except Exception as e:
                            logger.error(f"Error sending success notification: {str(e)}")
                else:
                    # Notify about error
                    if self.bot:
                        import asyncio
                        lesson_name = lesson.name or f"Заняття #{lesson.id}"
                        try:
                            asyncio.create_task(self.send_notification(
                                user.telegram_id,
                                f"❌ Не вдалося відмітитись на {lesson_name}: {result['message']}"
                            ))
                        except Exception as e:
                            logger.error(f"Error sending error notification: {str(e)}")
        
        except Exception as e:
            logger.error(f"Error checking lesson {lesson.id} for user {user.telegram_id}: {str(e)}")
            if self.bot:
                import asyncio
                try:
                    asyncio.create_task(self.send_notification(
                        user.telegram_id,
                        f"❌ Помилка перевірки відвідуваності: {str(e)}"
                    ))
                except Exception as notify_error:
                    logger.error(f"Error sending exception notification: {str(notify_error)}")
        
        finally:
            session.close()
