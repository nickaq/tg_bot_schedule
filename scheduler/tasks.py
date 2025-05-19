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
        # Add job to check attendance every CHECK_INTERVAL_MINUTES minutes
        self.scheduler.add_job(
            self._run_check_attendance, 
            'interval', 
            minutes=CHECK_INTERVAL_MINUTES,
            next_run_time=datetime.datetime.now(pytz.UTC) + datetime.timedelta(seconds=10)  # Start first check after 10 seconds
        )
        
        self.scheduler.start()
        
        # Load the schedule data
        self.schedule_parser.load_schedule()
        
        logger.info(f"Scheduler started. Checking attendance every {CHECK_INTERVAL_MINUTES} minutes")
        
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
            # Создаем новый цикл событий для текущего потока
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Запускаем асинхронную проверку напрямую в этом потоке
            loop.run_until_complete(self._run_check_attendance_async())
            
            # Закрываем цикл событий
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
            return True, None  # В случае ошибки вернуть True (предполагаем, что сейчас занятие)
        
    def stop(self):
        """Stop the scheduler"""
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")
            
    async def _run_check_attendance_async(self):
        """Run the attendance check for all users"""
        logger.info("Starting scheduled attendance check")
        current_time = datetime.datetime.now(pytz.timezone('Europe/Kiev'))
        
        # Check if it's class time based on the schedule
        is_class_time, class_info = self.schedule_parser.is_class_time(current_time)
        
        if not is_class_time:
            logger.info("Not class time, skipping attendance check")
            return
        
        if class_info:
            class_name = class_info.get('subject', 'Unknown')
            start_time = class_info['start_time'].strftime("%H:%M")
            end_time = class_info['end_time'].strftime("%H:%M")
            logger.info(f"Current class: {class_name} ({start_time}-{end_time})")
        
        session = get_db_session()
        try:
            # Get all active users with their lessons
            users = DatabaseManager.get_all_users(session)
            
            for user in users:
                try:
                    # Skip if user has no credentials or is inactive
                    if not user.moodle_username or not user.encrypted_password or not user.is_active:
                        continue
                        
                    # Skip if user has no active lessons
                    active_lessons = [lesson for lesson in user.lessons if lesson.is_active]
                    if not active_lessons:
                        continue
                    
                    # Since we've already checked if it's class time, just process the lessons
                    await self.check_user_attendances(user, active_lessons)
                    
                except Exception as e:
                    logger.error(f"Error checking attendance for user {user.telegram_id}: {str(e)}")
        
        except Exception as e:
            logger.error(f"Error in attendance check: {str(e)}")
        finally:
            session.close()
    
    async def check_all_attendances(self):
        """Check attendance for all active users and lessons"""
        logger.info("Starting attendance check for all users")
        
        session = get_db_session()
        try:
            # Get all active users with their lessons
            users = DatabaseManager.get_all_users(session)
            
            for user in users:
                try:
                    # Skip if user has no credentials or is inactive
                    if not user.moodle_username or not user.encrypted_password or not user.is_active:
                        continue
                        
                    # Skip if user has no active lessons
                    active_lessons = [lesson for lesson in user.lessons if lesson.is_active]
                    if not active_lessons:
                        continue
                    
                    # Process user's lessons
                    await self.check_user_attendances(user, active_lessons)
                    
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
            if not user.moodle_login or not user.moodle_password_encrypted:
                logger.warning(f"Missing credentials for user {user.telegram_id}")
                return
                
            # Initialize MoodleClient for this user
            client = MoodleClient(user.moodle_login, user.moodle_password_encrypted, is_encrypted=True)
            
            # Check if credentials are valid
            if not client.validate_credentials():
                logger.warning(f"Invalid Moodle credentials for user {user.telegram_id}")
                return
            
            logger.info(f"Checking {len(lessons)} lessons for user {user.telegram_id}")
            
            # Check if we're currently in class time
            is_class_time, current_class = self.check_is_class_time()
            
            # Current time in Kiev timezone
            current_time = datetime.now(pytz.timezone('Europe/Kiev'))
            matched_lessons = []
            
            if is_class_time and current_class:
                class_name = current_class.get('subject', 'Заняття')
                logger.info(f"Current class time detected: {class_name}")
                
                # Find lessons that match the current class
                for lesson in lessons:
                    # Skip inactive lessons
                    if not lesson.is_active:
                        continue
                    
                    # Check if this lesson matches the current class
                    is_matching = False
                    
                    # If the lesson has a name, check if it contains part of the current class name or vice versa
                    if lesson.name and class_name:
                        # Clean the names for better matching
                        lesson_name_clean = lesson.name.lower().replace(' ', '')
                        class_name_clean = class_name.lower().replace(' ', '')
                        
                        # Check for partial matches in both directions
                        if (lesson_name_clean in class_name_clean) or (class_name_clean in lesson_name_clean):
                            is_matching = True
                            logger.info(f"Lesson '{lesson.name}' matches current class '{class_name}'")
                    
                    # If no direct name match but we have a URL with the subject code, try to match that
                    if not is_matching and lesson.url:
                        # Extract potential subject codes from the URL
                        url_parts = lesson.url.split('/')
                        for part in url_parts:
                            # If any part of the URL matches a substring of the class name
                            if len(part) > 3 and part.lower() in class_name.lower():
                                is_matching = True
                                logger.info(f"Lesson URL '{part}' matches current class '{class_name}'")
                                break
                    
                    # If we can't match, we still add it to the list as we might want to check it anyway
                    # But mark it for special handling
                    matched_lessons.append((lesson, is_matching))
                
                # If we have at least one matching lesson, only mark those
                has_matching = any(is_matching for _, is_matching in matched_lessons)
                
                if matched_lessons:
                    for lesson, is_matching in matched_lessons:
                        try:
                            # Skip non-matching lessons if we have at least one match
                            if has_matching and not is_matching:
                                logger.info(f"Skipping lesson {lesson.id} '{lesson.name}' as it doesn't match current class '{class_name}'")
                                continue
                            
                            # Check this lesson
                            await self.check_lesson_attendance(user, lesson, client)
                            
                            # Send specific notification for matched lessons
                            if is_matching and self.bot:
                                try:
                                    lesson_name = lesson.name or f"Заняття #{lesson.id}"
                                    await self.bot.send_message(
                                        chat_id=user.telegram_id,
                                        text=f"✅ Відмічаюсь на занятті що збігається з розкладом: {class_name} ({lesson_name})"
                                    )
                                except Exception as e:
                                    logger.error(f"Error sending match notification: {e}")
                                
                        except Exception as e:
                            logger.error(f"Error checking lesson {lesson.id} for user {user.telegram_id}: {e}")
                else:
                    logger.info(f"No active lessons found for user {user.telegram_id} to match with class '{class_name}'")
            else:
                logger.info(f"No current class time detected, skipping attendance check for user {user.telegram_id}")
                # Optionally notify user that there's no class at the moment if debug needed
                # This is commented out to avoid spamming users when there are no classes
                # if self.bot:
                #     try:
                #         await self.bot.send_message(
                #             chat_id=user.telegram_id,
                #             text="ℹ️ Зараз немає занять, відмічатися не потрібно."
                #         )
                #     except Exception as e:
                #         logger.error(f"Error sending notification to user {user.telegram_id}: {e}")
            
            # Add a small delay between requests to avoid rate limiting
            await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"Error processing lessons for user {user.telegram_id}: {e}")
                
    # Вспомогательный метод для отправки уведомлений
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
