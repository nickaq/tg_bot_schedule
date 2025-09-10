import os
import re
import csv
import logging
import io
from datetime import datetime, timedelta, date, time
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
        
        try:
            self.schedule = []
            
            # Read the file with different encodings
            content = None
            text = None
            for encoding in ['utf-8', 'cp1251', 'iso-8859-1']:
                try:
                    with open(self.csv_path, 'r', encoding=encoding) as f:
                        text = f.read()
                        break
                except UnicodeDecodeError:
                    continue
            
            if text is None:
                logger.error("Could not decode the CSV file with any encoding")
                self._load_example_data()
                return True
            
            # Remove problematic characters
            text = text.replace('\ufffd', ' ')
            
            # Parse using CSV module
            csv_reader = csv.reader(io.StringIO(text), delimiter=',')
            rows = list(csv_reader)
            
            # Log some diagnostic info
            logger.info(f"CSV file has {len(rows)} rows")
            if len(rows) > 0:
                logger.info(f"First row has {len(rows[0])} fields: {rows[0]}")
            
            # Skip header row if present
            if len(rows) > 0 and any(['Тема' in str(rows[0]), 'Дата' in str(rows[0])]):
                rows = rows[1:]
            
            for row in rows:
                if not row or len(row) < 5:  # we need at least subject, start date, start time, end date, end time
                    continue
                
                try:
                    # Extract data fields - clean quotes and spaces
                    subject = row[0].strip(' "').strip()
                    start_date_str = row[1].strip(' "').strip()
                    start_time_str = row[2].strip(' "').strip()
                    end_date_str = row[3].strip(' "').strip()
                    end_time_str = row[4].strip(' "').strip()
                    
                    logger.debug(f"Processing row: {subject}, {start_date_str}, {start_time_str}, {end_date_str}, {end_time_str}")
                    
                    # Parse dates and times
                    lesson_date = datetime.strptime(start_date_str, "%d.%m.%Y").date()
                    start_time = datetime.strptime(start_time_str, "%H:%M:%S").time()
                    end_time = datetime.strptime(end_time_str, "%H:%M:%S").time()
                    
                    # Add to schedule
                    self.schedule.append({
                        'date': lesson_date,
                        'start_time': start_time,
                        'end_time': end_time,
                        'subject': subject or "Заняття"
                    })
                    
                except Exception as e:
                    # Try using regex as a fallback
                    line = ','.join(row)
                    try:
                        # Define regex patterns for date and time extraction
                        date_pattern = r'(\d{2}\.\d{2}\.\d{4})'
                        time_pattern = r'(\d{2}:\d{2}:\d{2})'
                        
                        # Extract dates and times using regex
                        dates = re.findall(date_pattern, line)
                        times = re.findall(time_pattern, line)
                        
                        if not dates or len(times) < 2:
                            logger.debug(f"Regex fallback: not enough date/time data in line: {line}")
                            continue
                        
                        # Parse date and times
                        lesson_date = datetime.strptime(dates[0], "%d.%m.%Y").date()
                        start_time = datetime.strptime(times[0], "%H:%M:%S").time()
                        end_time = datetime.strptime(times[1], "%H:%M:%S").time()
                        
                        # Extract subject from the row
                        subject = "Заняття"  # Default value
                        if row and row[0]:
                            subject = row[0].strip(' "').strip() or subject
                        
                        # Add to schedule
                        self.schedule.append({
                            'date': lesson_date,
                            'start_time': start_time,
                            'end_time': end_time,
                            'subject': subject
                        })
                        
                    except Exception as e2:
                        logger.debug(f"Failed to process row {row}: {e}, then: {e2}")
            
            # If no classes found, use example data
            if not self.schedule:
                logger.warning("No classes found, using example data")
                self._load_example_data()
            else:
                # Sort by date and time
                self.schedule.sort(key=lambda x: (x['date'], x['start_time']))
            
            logger.info(f"Successfully loaded {len(self.schedule)} classes")
            self.is_loaded = True
            return True
            
        except Exception as e:
            logger.error(f"Error loading schedule: {e}")
            # Load example data as fallback
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
                return True, None  # Default to True if schedule can't be loaded
        
        if current_time is None:
            current_time = datetime.now(self.kiev_tz)
        
        current_date = current_time.date()
        current_time_no_tz = current_time.replace(tzinfo=None).time()
        
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
            # Include classes that are today but haven't ended yet
            if session['date'] == now.date() and \
               now.time() <= session['end_time']:
                upcoming_classes.append(session)
            # Include future classes within the date range
            elif now.date() < session['date'] <= end_date:
                upcoming_classes.append(session)
        
        return upcoming_classes
    
    def format_schedule(self, classes):
        """Format a list of classes into a readable schedule."""
        if not classes:
            return "Немає запланованих занять на цей період."
        
        # Group classes by date
        classes_by_date = {}
        for cls in classes:
            date_str = cls['date'].strftime("%d.%m.%Y")
            if date_str not in classes_by_date:
                classes_by_date[date_str] = []
            classes_by_date[date_str].append(cls)
        
        # Format each day's schedule
        result = ["📅 Розклад занять:"]
        for date_str in sorted(classes_by_date.keys()):
            # Get day of week name
            date_obj = datetime.strptime(date_str, "%d.%m.%Y")
            weekday = ['Понеділок', 'Вівторок', 'Середа', 'Четвер', "П'ятниця", 'Субота', 'Неділя'][date_obj.weekday()]
            
            result.append(f"\n📌 {date_str} ({weekday})")
            for cls in sorted(classes_by_date[date_str], key=lambda x: x['start_time']):
                start_time = cls['start_time'].strftime("%H:%M")
                end_time = cls['end_time'].strftime("%H:%M")
                subject = cls.get('subject', 'Занятие')
                
                result.append(f"🕒 {start_time} - {end_time}: {subject}")
        
        return "\n".join(result)
        
    def get_weekly_schedule(self):
        """Get a formatted weekly schedule organized by weekday."""
        if not self.is_loaded:
            if not self.load_schedule():
                logger.error("Failed to load schedule")
                return "❌ Не вдалося завантажити розклад занять."
        
        # First, identify the current week's boundaries
        today = datetime.now(self.kiev_tz).date()
        start_of_week = today - timedelta(days=today.weekday())  # Monday of current week
        end_of_week = start_of_week + timedelta(days=6)  # Sunday of current week
        
        # Group classes by weekday (0=Monday through 6=Sunday)
        weekday_classes = {i: [] for i in range(7)}
        
        for session in self.schedule:
            if start_of_week <= session['date'] <= end_of_week:
                weekday = session['date'].weekday()
                weekday_classes[weekday].append(session)
        
        # Format the weekly schedule
        weekday_names = ['Понеділок', 'Вівторок', 'Середа', 'Четвер', "П'ятниця", 'Субота', 'Неділя']
        result = ["📅 Розклад на тиждень:"]
        
        for day_num, day_name in enumerate(weekday_names):
            classes = weekday_classes[day_num]
            day_date = start_of_week + timedelta(days=day_num)
            date_str = day_date.strftime("%d.%m")
            
            # Highlight current day
            if day_date == today:
                result.append(f"\n🔹 <b>{day_name} ({date_str}) - СЬОГОДНІ</b>")
            else:
                result.append(f"\n🔸 <b>{day_name} ({date_str})</b>")
            
            if not classes:
                result.append("  ┗ Немає занять")
            else:
                for cls in sorted(classes, key=lambda x: x['start_time']):
                    start_time = cls['start_time'].strftime("%H:%M")
                    end_time = cls['end_time'].strftime("%H:%M")
                    subject = cls.get('subject', 'Занятие')
                    
                    result.append(f"  ┗ 🕒 {start_time} - {end_time}: {subject}")
        
        return "\n".join(result)

    def get_schedule_for_date(self, current_dt):
        """Return the list of sessions for the given date.
        If current_dt is None, use now in Kyiv tz.
        """
        if not self.is_loaded:
            if not self.load_schedule():
                logger.error("Failed to load schedule")
                return []

        if current_dt is None:
            current_dt = datetime.now(self.kiev_tz)

        # Normalize to Kyiv date
        if current_dt.tzinfo is not None:
            current_dt = current_dt.astimezone(self.kiev_tz)
        day = current_dt.date()

        return [s for s in self.schedule if s['date'] == day]
