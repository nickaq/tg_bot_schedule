import os
import csv
import logging
from datetime import datetime, timedelta, time
import pytz

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SimpleScheduleParser:
    """Simple parser for TimeTable CSV files."""

    def __init__(self, csv_path):
        """Initialize with the path to the CSV file."""
        self.csv_path = csv_path
        self.schedule = []
        self.is_loaded = False
        self.kiev_tz = pytz.timezone('Europe/Kiev')

    def load_schedule(self):
        """Load and parse the schedule from the CSV file."""
        if not os.path.exists(self.csv_path):
            logger.error(f"Schedule file not found: {self.csv_path}")
            return False

        # Принудительно ставим ISO-8859-1
        encoding = 'cp1251'
        logger.info(f"Opening CSV with encoding: {encoding}")

        try:
            with open(self.csv_path, 'r', encoding=encoding, errors='replace') as f:
                reader = csv.DictReader(f, delimiter=',')
                for row in reader:
                    try:
                        # Парсим даты и время
                        start_date = datetime.strptime(row['Дата начала'], "%d.%m.%Y").date()
                        start_time = datetime.strptime(row['Время начала'], "%H:%M:%S").time()
                        end_date   = datetime.strptime(row['Дата завершения'], "%d.%m.%Y").date()
                        end_time   = datetime.strptime(row['Время завершения'], "%H:%M:%S").time()

                        # Тема занятия (fallback на Описание)
                        subject = row.get('Тема', '').strip()
                        if not subject:
                            subject = row.get('Описание', 'Занятие').strip()

                        # Добавляем в расписание
                        self.schedule.append({
                            'date':       start_date,
                            'start_time': start_time,
                            'end_time':   end_time,
                            'subject':    subject
                        })

                    except Exception as e:
                        logger.debug(f"Skipping row due to parse error: {e}")

            # Если не нашли ни одной записи — грузим пример
            if not self.schedule:
                logger.warning("No classes found, loading example data")
                self._load_example_data()
            else:
                self.schedule.sort(key=lambda x: (x['date'], x['start_time']))

            logger.info(f"Successfully loaded {len(self.schedule)} classes")
            self.is_loaded = True
            return True

        except Exception as e:
            logger.error(f"Error loading schedule: {e}")
            self._load_example_data()
            return True

    def _load_example_data(self):
        """Load example schedule data for testing."""
        today = datetime.now(self.kiev_tz).date()
        tomorrow = today + timedelta(days=1)

        self.schedule = [
            {
                'date': today,
                'start_time': time(9, 30),
                'end_time': time(11, 5),
                'subject': 'Программирование'
            },
            {
                'date': today,
                'start_time': time(11, 15),
                'end_time': time(12, 50),
                'subject': 'Математика'
            },
            {
                'date': tomorrow,
                'start_time': time(13, 10),
                'end_time': time(14, 45),
                'subject': 'Физика'
            }
        ]
        self.is_loaded = True
        logger.info("Loaded example schedule data")

    def is_class_time(self, current_time=None):
        """Check if it's currently class time based on the schedule."""
        if not self.is_loaded:
            if not self.load_schedule():
                logger.error("Failed to load schedule")
                return True, None

        if current_time is None:
            current_time = datetime.now(self.kiev_tz)

        current_date = current_time.date()
        current_time_no_tz = current_time.time()

        for session in self.schedule:
            if session['date'] == current_date and \
               session['start_time'] <= current_time_no_tz <= session['end_time']:
                return True, session

        return False, None

    def get_upcoming_classes(self, days=7):
        """Get upcoming classes for the specified number of days."""
        if not self.is_loaded:
            if not self.load_schedule():
                logger.error("Failed to load schedule")
                return []

        now = datetime.now(self.kiev_tz)
        end_date = now.date() + timedelta(days=days)

        upcoming_classes = []
        for session in self.schedule:
            if session['date'] == now.date() and now.time() <= session['end_time']:
                upcoming_classes.append(session)
            elif now.date() < session['date'] <= end_date:
                upcoming_classes.append(session)

        return upcoming_classes

    def format_schedule(self, classes):
        """Format a list of classes into a readable schedule."""
        if not classes:
            return "Немає запланованих занять на цей період."

        classes_by_date = {}
        for cls in classes:
            date_str = cls['date'].strftime("%d.%m.%Y")
            classes_by_date.setdefault(date_str, []).append(cls)

        result = ["📅 Розклад занять:"]
        for date_str in sorted(classes_by_date.keys()):
            date_obj = datetime.strptime(date_str, "%d.%m.%Y")
            weekday = ['Понеділок','Вівторок','Середа','Четвер',"П'ятниця",'Субота','Неділя'][date_obj.weekday()]
            result.append(f"\n📌 {date_str} ({weekday})")
            for cls in sorted(classes_by_date[date_str], key=lambda x: x['start_time']):
                start = cls['start_time'].strftime("%H:%M")
                end   = cls['end_time'].strftime("%H:%M")
                subj  = cls.get('subject', 'Занятие')
                result.append(f"🕒 {start} - {end}: {subj}")

        return "\n".join(result)
