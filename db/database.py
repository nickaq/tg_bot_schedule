from sqlalchemy.orm import Session
from datetime import datetime
from .models import User, Lesson, get_db_session


class DatabaseManager:
    """Manager for database operations"""

    @staticmethod
    def get_user_by_telegram_id(session: Session, telegram_id: int) -> User:
        """Get user by Telegram ID"""
        return session.query(User).filter(User.telegram_id == telegram_id).first()

    @staticmethod
    def create_user(session: Session, telegram_id: int) -> User:
        """Create a new user"""
        user = User(telegram_id=telegram_id)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    @staticmethod
    def set_user_credentials(session: Session, telegram_id: int, username: str, password: str) -> User:
        """Set or update user credentials"""
        user = DatabaseManager.get_user_by_telegram_id(session, telegram_id)
        if not user:
            user = DatabaseManager.create_user(session, telegram_id)
        
        user.moodle_username = username
        user.set_password(password)
        session.commit()
        session.refresh(user)
        return user

    @staticmethod
    def add_lesson(session: Session, telegram_id: int, url: str, name: str = None) -> Lesson:
        """Add a new lesson for a user"""
        user = DatabaseManager.get_user_by_telegram_id(session, telegram_id)
        if not user:
            return None
        
        lesson = Lesson(user_id=user.id, url=url, name=name)
        session.add(lesson)
        session.commit()
        session.refresh(lesson)
        return lesson

    @staticmethod
    def get_user_lessons(session: Session, telegram_id: int, active_only: bool = False):
        """Get all lessons for a user"""
        user = DatabaseManager.get_user_by_telegram_id(session, telegram_id)
        if not user:
            return []
        
        query = session.query(Lesson).filter(Lesson.user_id == user.id)
        if active_only:
            query = query.filter(Lesson.active == True)
        
        return query.all()

    @staticmethod
    def remove_lesson(session: Session, telegram_id: int, lesson_id: int) -> bool:
        """Remove a lesson for a user"""
        user = DatabaseManager.get_user_by_telegram_id(session, telegram_id)
        if not user:
            return False
        
        lesson = session.query(Lesson).filter(
            Lesson.id == lesson_id,
            Lesson.user_id == user.id
        ).first()
        
        if not lesson:
            return False
        
        session.delete(lesson)
        session.commit()
        return True

    @staticmethod
    def toggle_lesson_status(session: Session, telegram_id: int, lesson_id: int) -> Lesson:
        """Toggle active status for a lesson"""
        user = DatabaseManager.get_user_by_telegram_id(session, telegram_id)
        if not user:
            return None
        
        lesson = session.query(Lesson).filter(
            Lesson.id == lesson_id,
            Lesson.user_id == user.id
        ).first()
        
        if not lesson:
            return None
        
        lesson.active = not lesson.active
        session.commit()
        session.refresh(lesson)
        return lesson

    @staticmethod
    def get_all_active_users_and_lessons(session: Session):
        """Get all active users with their active lessons for attendance checking"""
        users = session.query(User).filter(User.active == True).all()
        result = []
        
        for user in users:
            active_lessons = session.query(Lesson).filter(
                Lesson.user_id == user.id,
                Lesson.active == True
            ).all()
            
            if active_lessons:
                result.append((user, active_lessons))
        
        return result

    @staticmethod
    def update_lesson_check_time(session: Session, lesson_id: int):
        """Update the last checked time for a lesson"""
        lesson = session.query(Lesson).filter(Lesson.id == lesson_id).first()
        if lesson:
            lesson.last_checked = datetime.utcnow()
            session.commit()

    @staticmethod
    def update_lesson_mark_time(session: Session, lesson_id: int):
        """Update the last marked time for a lesson"""
        lesson = session.query(Lesson).filter(Lesson.id == lesson_id).first()
        if lesson:
            lesson.last_marked = datetime.utcnow()
            session.commit()
