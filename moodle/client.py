import requests
from bs4 import BeautifulSoup
import logging
import re
import time
from datetime import datetime, timedelta
import json
from config import MOODLE_BASE_URL, LOGIN_URL

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MoodleClient:
    """Client for interacting with Moodle LMS"""
    
    def __init__(self, username=None, password=None, is_encrypted=False):
        self.username = username
        
        # Handle encrypted passwords
        if is_encrypted and password:
            try:
                from cryptography.fernet import Fernet
                from config import ENCRYPTION_KEY
                if not ENCRYPTION_KEY:
                    logger.error("ENCRYPTION_KEY not found in config")
                    self.password = None
                else:
                    fernet = Fernet(ENCRYPTION_KEY.encode())
                    self.password = fernet.decrypt(password.encode()).decode()
            except Exception as e:
                logger.error(f"Error decrypting password: {e}")
                self.password = None
        else:
            self.password = password
        
        self.session = requests.Session()
        # Отключаем проверку SSL-сертификата (не рекомендуется для продакшена, но решает проблему с сертификатом)
        self.session.verify = False
        # Подавляем предупреждения о небезопасном SSL
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self.is_logged_in = False
        
        # Кэш для хранения информации о курсах и доступных отметках
        self.courses_cache = {}  # {course_id: {name, url, last_updated}}
        self.attendance_cache = {}  # {attendance_url: {status, last_checked}}
        self.cache_ttl = 300  # Время жизни кэша в секундах (5 минут)
    
    def validate_credentials(self):
        """Validate if the provided credentials can successfully log in to DL"""
        if not self.username or not self.password:
            logger.warning("Username or password not provided")
            return False
        
        # Try to log in and return the result
        login_result = self.login()
        logger.info(f"Credentials validation {'successful' if login_result else 'failed'} for user {self.username}")
        return login_result
    
    def login(self):
        """Log in to Moodle"""
        if not self.username or not self.password:
            logger.error("Username or password not provided")
            return False
        
        try:
            # Get login page to extract form token
            login_page = self.session.get(LOGIN_URL)
            soup = BeautifulSoup(login_page.text, 'html.parser')
            
            # Find login form
            login_form = soup.find('form', {'id': 'login'})
            if not login_form:
                logger.error("Could not find login form")
                return False
            
            # Extract token
            token_input = login_form.find('input', {'name': 'logintoken'})
            if not token_input:
                logger.error("Could not find login token")
                return False
            
            token = token_input.get('value', '')
            
            # Prepare login payload
            payload = {
                'username': self.username,
                'password': self.password,
                'logintoken': token,
                'anchor': ''
            }
            
            # Submit login form
            login_response = self.session.post(LOGIN_URL, data=payload)
            
            # Check if login was successful
            self.is_logged_in = 'loginerrors' not in login_response.url
            if self.is_logged_in:
                logger.info(f"Successfully logged in as {self.username}")
            else:
                logger.error(f"Failed to log in as {self.username}")
            
            return self.is_logged_in
        
        except Exception as e:
            logger.error(f"Error during login: {str(e)}")
            return False
    
    def get_dashboard(self):
        """Get user's Moodle dashboard to find all active courses"""
        if not self.is_logged_in:
            logged_in = self.login()
            if not logged_in:
                return None
        
        try:
            # Get the dashboard page
            dashboard_url = f"{MOODLE_BASE_URL}/my/"
            response = self.session.get(dashboard_url)
            if response.status_code != 200:
                logger.error(f"Failed to load dashboard: {response.status_code}")
                return None
            
            return response.text
        except Exception as e:
            logger.error(f"Error getting dashboard: {str(e)}")
            return None
    
    def scan_for_courses(self):
        """Scan the dashboard to find all active courses"""
        dashboard_html = self.get_dashboard()
        if not dashboard_html:
            return []
        
        soup = BeautifulSoup(dashboard_html, 'html.parser')
        courses = []
        
        # Look for course cards or links
        course_cards = soup.find_all('div', {'class': re.compile(r'course|coursebox')})
        if not course_cards:
            # Try finding course links directly
            course_links = soup.find_all('a', {'href': re.compile(r'/course/view.php')})
            for link in course_links:
                course_url = link.get('href')
                course_name = link.text.strip()
                if course_url and course_name:
                    course_id = re.search(r'id=(\d+)', course_url)
                    if course_id:
                        course_id = course_id.group(1)
                        courses.append({
                            'id': course_id,
                            'name': course_name,
                            'url': course_url
                        })
        else:
            for card in course_cards:
                link = card.find('a', {'href': re.compile(r'/course/view.php')})
                if link:
                    course_url = link.get('href')
                    course_name = link.text.strip()
                    if not course_name:
                        # Try to find course name in another element
                        title = card.find('h3') or card.find('div', {'class': 'coursename'})
                        if title:
                            course_name = title.text.strip()
                    
                    course_id = re.search(r'id=(\d+)', course_url)
                    if course_id:
                        course_id = course_id.group(1)
                        courses.append({
                            'id': course_id,
                            'name': course_name,
                            'url': course_url
                        })
        
        # Update cache
        now = time.time()
        for course in courses:
            self.courses_cache[course['id']] = {
                'name': course['name'],
                'url': course['url'],
                'last_updated': now
            }
        
        return courses
    
    def scan_course_for_attendance(self, course_url):
        """Scan a course page for attendance activities"""
        if not self.is_logged_in:
            logged_in = self.login()
            if not logged_in:
                return []
        
        try:
            # Get the course page
            response = self.session.get(course_url)
            if response.status_code != 200:
                logger.error(f"Failed to load course page: {response.status_code}")
                return []
            
            soup = BeautifulSoup(response.text, 'html.parser')
            attendance_links = []
            
            # Look for attendance modules
            attendance_modules = soup.find_all('li', {'class': re.compile(r'modtype_attendance|attendance')})
            for module in attendance_modules:
                link = module.find('a')
                if link:
                    href = link.get('href')
                    name = link.text.strip()
                    if href:
                        attendance_links.append({
                            'url': href,
                            'name': name
                        })
            
            # Also search for links containing 'attendance.php'
            attendance_urls = soup.find_all('a', {'href': re.compile(r'attendance.php')})
            for url in attendance_urls:
                href = url.get('href')
                name = url.text.strip()
                if href and not any(link['url'] == href for link in attendance_links):
                    attendance_links.append({
                        'url': href,
                        'name': name
                    })
            
            return attendance_links
        except Exception as e:
            logger.error(f"Error scanning course for attendance: {str(e)}")
            return []
    
    def find_all_active_attendance_marks(self):
        """Intelligent method to find all active attendance marks across all courses"""
        # First check if we need to refresh course cache
        now = time.time()
        courses_expired = not self.courses_cache or all(
            now - course_data['last_updated'] > self.cache_ttl 
            for course_data in self.courses_cache.values()
        )
        
        if courses_expired:
            logger.info("Course cache expired, refreshing course list")
            courses = self.scan_for_courses()
        else:
            logger.info("Using cached course list")
            courses = [
                {'id': course_id, 'name': data['name'], 'url': data['url']}
                for course_id, data in self.courses_cache.items()
            ]
        
        active_attendances = []
        
        # Scan each course for attendance activities
        for course in courses:
            attendance_links = self.scan_course_for_attendance(course['url'])
            for attendance in attendance_links:
                # Check if this attendance link is active
                check_result = self.check_attendance(attendance['url'])
                if check_result['status'] == 'available':
                    active_attendances.append({
                        'course_name': course['name'],
                        'attendance_name': attendance['name'],
                        'url': attendance['url'],
                        'check_result': check_result
                    })
        
        return active_attendances
    
    def check_attendance(self, lesson_url):
        """Check if attendance marking is available for a lesson"""
        # Check cache first
        now = time.time()
        if lesson_url in self.attendance_cache:
            cache_entry = self.attendance_cache[lesson_url]
            if now - cache_entry['last_checked'] < self.cache_ttl:
                logger.info(f"Using cached attendance status for {lesson_url}")
                return cache_entry['status']
        
        if not self.is_logged_in:
            logged_in = self.login()
            if not logged_in:
                return {'status': 'error', 'message': 'Not logged in'}
        
        try:
            # Get the lesson page
            response = self.session.get(lesson_url)
            if response.status_code != 200:
                return {'status': 'error', 'message': f'Failed to load lesson page: {response.status_code}'}
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Option 1: Direct "Submit attendance" button
            attendance_btn = soup.find('input', {'value': re.compile(r'отметиться|submit attendance', re.I)})
            
            # Option 2: Exact link text matching "Submit attendance"
            if not attendance_btn:
                submit_attendance_links = soup.find_all('a', text="Submit attendance")
                if submit_attendance_links:
                    for link in submit_attendance_links:
                        attendance_form_url = link.get('href')
                        if attendance_form_url and 'attendance.php' in attendance_form_url:
                            logger.info(f"Found 'Submit attendance' link: {attendance_form_url}")
                            result = {'status': 'available', 'form_url': attendance_form_url}
                            # Update cache
                            self.attendance_cache[lesson_url] = {
                                'status': result,
                                'last_checked': now
                            }
                            return result
            
            # Option 3: Attendance status link with regex pattern
            if not attendance_btn:
                attendance_link = soup.find('a', text=re.compile(r'отметиться|mark attendance|submit attendance', re.I))
                if attendance_link:
                    attendance_form_url = attendance_link.get('href')
                    if attendance_form_url:
                        logger.info(f"Found attendance link with regex: {attendance_form_url}")
                        result = {'status': 'available', 'form_url': attendance_form_url}
                        # Update cache
                        self.attendance_cache[lesson_url] = {
                            'status': result,
                            'last_checked': now
                        }
                        return result
            
            # Option 4: Check for "Submit attendance" or similar text anywhere on the page
            submit_text = soup.find(text=re.compile(r'submit attendance|mark attendance|присутствие', re.I))
            if submit_text:
                # Try to find parent link
                parent = submit_text.parent
                while parent and parent.name != 'a' and parent.name != 'body':
                    parent = parent.parent
                
                if parent and parent.name == 'a':
                    attendance_form_url = parent.get('href')
                    if attendance_form_url:
                        logger.info(f"Found attendance text with parent link: {attendance_form_url}")
                        result = {'status': 'available', 'form_url': attendance_form_url}
                        # Update cache
                        self.attendance_cache[lesson_url] = {
                            'status': result,
                            'last_checked': now
                        }
                        return result
            
            # Option 5: Check for attendance section
            attendance_section = soup.find(['div', 'section'], {'class': re.compile(r'attendance')})
            if attendance_section:
                # Look for form or links in the attendance section
                form = attendance_section.find('form')
                if form:
                    result = {'status': 'available', 'form_action': form.get('action')}
                    # Update cache
                    self.attendance_cache[lesson_url] = {
                        'status': result,
                        'last_checked': now
                    }
                    return result
            
            if attendance_btn:
                result = {'status': 'available', 'button_found': True}
                # Update cache
                self.attendance_cache[lesson_url] = {
                    'status': result,
                    'last_checked': now
                }
                return result
            
            # No attendance found
            result = {'status': 'not_available', 'message': 'No attendance marking option found'}
            # Update cache
            self.attendance_cache[lesson_url] = {
                'status': result,
                'last_checked': now
            }
            return result
                
        except Exception as e:
            logger.error(f"Error checking attendance: {str(e)}")
            return {'status': 'error', 'message': str(e)}
                
    def submit_attendance(self, form_url):
        """Submit attendance form using the provided form URL"""
        if not self.is_logged_in:
            logged_in = self.login()
            if not logged_in:
                return {'status': 'error', 'message': 'Not logged in'}

        try:
            # Load the form page
            logger.info(f"Getting attendance form: {form_url}")
            response = self.session.get(form_url)
            if response.status_code != 200:
                return {'status': 'error', 'message': f'Failed to load form: {response.status_code}'}

            soup = BeautifulSoup(response.text, 'html.parser')
            form = soup.find('form')
            if not form:
                return {'status': 'error', 'message': 'Attendance form not found'}

            # Build payload from inputs
            payload = {}
            radios = []
            for inp in form.find_all('input'):
                name = inp.get('name')
                if not name:
                    continue
                itype = (inp.get('type') or '').lower()
                if itype in ['radio', 'checkbox']:
                    if itype == 'radio':
                        radios.append(inp)
                    continue
                payload[name] = inp.get('value', '')

            # Try to pick "Present"-like status
            chosen = False
            for r in radios:
                label_text = ''
                label = r.find_parent('label')
                if label:
                    label_text = label.get_text(strip=True).lower()
                if any(k in label_text for k in ['present', 'присутств', 'присутн', 'відвідав', 'відвідування']):
                    payload[r.get('name')] = r.get('value')
                    chosen = True
                    break
            if not chosen and radios:
                payload[radios[0].get('name')] = radios[0].get('value')

            # Determine action
            action = form.get('action') or form_url
            if action.startswith('/'):
                action = f"{MOODLE_BASE_URL}{action}"

            post = self.session.post(action, data=payload)
            if post.status_code != 200:
                return {'status': 'error', 'message': f'Failed to submit form: {post.status_code}'}

            body = post.text.lower()
            success_markers = ['attendance has been recorded', 'успешно', 'успішно', 'відмічено', 'attendance: status set']
            if any(m in body for m in success_markers):
                return {'status': 'success'}
            return {'status': 'unknown', 'message': 'Submission response unclear'}
        except Exception as e:
            logger.error(f"Error submitting attendance: {str(e)}")
            return {'status': 'error', 'message': str(e)}

    def mark_attendance(self, lesson_url):
        """Check availability and submit attendance when possible"""
        try:
            check = self.check_attendance(lesson_url)
            if check.get('status') != 'available':
                return {'status': 'not_available', 'message': check.get('message', 'Not available')}
            form_url = check.get('form_url') or check.get('form_action') or lesson_url
            return self.submit_attendance(form_url)
        except Exception as e:
            logger.error(f"Error in mark_attendance: {str(e)}")
            return {'status': 'error', 'message': str(e)}
