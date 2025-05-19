from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
import datetime
from cryptography.fernet import Fernet
from config import ENCRYPTION_KEY, DATABASE_URL

Base = declarative_base()

# Initialize encryption
fernet = Fernet(ENCRYPTION_KEY.encode() if ENCRYPTION_KEY else Fernet.generate_key())


class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    moodle_username = Column(String, nullable=True)
    encrypted_password = Column(String, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    # Relationship with Lesson
    lessons = relationship("Lesson", back_populates="user", cascade="all, delete-orphan")
    
    def set_password(self, password):
        """Encrypt and save the password"""
        if password:
            self.encrypted_password = fernet.encrypt(password.encode()).decode()
    
    def get_password(self):
        """Decrypt and return the password"""
        if self.encrypted_password:
            return fernet.decrypt(self.encrypted_password.encode()).decode()
        return None


class Lesson(Base):
    __tablename__ = 'lessons'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete="CASCADE"), nullable=False)
    url = Column(String, nullable=False)
    name = Column(String, nullable=True)  # Optional lesson name
    active = Column(Boolean, default=True)  # Whether to check for attendance
    last_checked = Column(DateTime, nullable=True)
    last_marked = Column(DateTime, nullable=True)
    
    # Relationship with User
    user = relationship("User", back_populates="lessons")


# Database initialization
engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db_session():
    """Get database session."""
    session = SessionLocal()
    try:
        return session
    finally:
        session.close()
