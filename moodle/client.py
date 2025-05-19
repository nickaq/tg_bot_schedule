import requests
from bs4 import BeautifulSoup
import logging
import re
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
    
    def check_attendance(self, lesson_url):
        """Check if attendance marking is available for a lesson"""
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
            
            # Look for attendance button (could be various forms depending on Moodle version)
            # Option 1: Direct "Submit attendance" button
            attendance_btn = soup.find('input', {'value': re.compile(r'отметиться|submit attendance', re.I)})
            
            # Option 2: Attendance status link
            if not attendance_btn:
                attendance_link = soup.find('a', text=re.compile(r'отметиться|mark attendance', re.I))
                if attendance_link:
                    attendance_form_url = attendance_link.get('href')
                    if attendance_form_url:
                        return {'status': 'available', 'form_url': attendance_form_url}
            
            # Option 3: Check for attendance section
            if not attendance_btn:
                attendance_section = soup.find('div', {'class': re.compile(r'attendance')})
                if attendance_section:
                    # Look for form or links in the attendance section
                    form = attendance_section.find('form')
                    if form:
                        return {'status': 'available', 'form_action': form.get('action')}
            
            if attendance_btn:
                return {'status': 'available', 'button_found': True}
            else:
                return {'status': 'not_available', 'message': 'No attendance marking option found'}
                
        except Exception as e:
            logger.error(f"Error checking attendance: {str(e)}")
            return {'status': 'error', 'message': str(e)}
    
    def mark_attendance(self, lesson_url):
        """Mark attendance for a lesson"""
        check_result = self.check_attendance(lesson_url)
        
        if check_result['status'] != 'available':
            return check_result
            
        try:
            # Depending on the type of attendance marking found
            if 'form_url' in check_result:
                # Case 1: Follow the link to attendance form
                form_response = self.session.get(check_result['form_url'])
                form_soup = BeautifulSoup(form_response.text, 'html.parser')
                
                # Look for the attendance form
                form = form_soup.find('form', {'id': re.compile(r'attform|attendance')})
                if not form:
                    return {'status': 'error', 'message': 'Could not find attendance form'}
                
                # Get form action
                form_action = form.get('action', '')
                
                # Find "Present" radio button
                present_option = form_soup.find('input', {
                    'type': 'radio', 
                    'name': re.compile(r'status|attendance'),
                    'value': re.compile(r'1|present')  # Usually value 1 means "Present"
                })
                
                if not present_option:
                    return {'status': 'error', 'message': 'Could not find "Present" option'}
                
                # Extract all form data
                form_data = {}
                for input_tag in form.find_all('input'):
                    name = input_tag.get('name')
                    value = input_tag.get('value', '')
                    if name:
                        form_data[name] = value
                
                # Set "Present" status
                status_field_name = present_option.get('name')
                form_data[status_field_name] = present_option.get('value')
                
                # Submit the form
                submit_response = self.session.post(form_action, data=form_data)
                
                if submit_response.status_code == 200:
                    return {'status': 'success', 'message': 'Attendance marked successfully'}
                else:
                    return {'status': 'error', 'message': f'Failed to submit attendance form: {submit_response.status_code}'}
            
            elif 'form_action' in check_result:
                # Similar to above, but we already have the form action
                form_action = check_result['form_action']
                form_response = self.session.get(lesson_url)
                form_soup = BeautifulSoup(form_response.text, 'html.parser')
                
                # Find the form
                form = form_soup.find('form', {'action': re.compile(form_action)})
                if not form:
                    return {'status': 'error', 'message': 'Could not find attendance form'}
                
                # Rest of processing similar to above case
                # ...extract form data and submit...
            
            elif 'button_found' in check_result:
                # Direct form submission case
                response = self.session.get(lesson_url)
                soup = BeautifulSoup(response.text, 'html.parser')
                
                form = soup.find('form', {'method': 'post'})
                if not form:
                    return {'status': 'error', 'message': 'Could not find form for direct submission'}
                
                form_action = form.get('action', lesson_url)
                form_data = {}
                
                for input_tag in form.find_all('input'):
                    name = input_tag.get('name')
                    value = input_tag.get('value', '')
                    if name:
                        form_data[name] = value
                
                # Submit the form
                submit_response = self.session.post(form_action, data=form_data)
                
                if submit_response.status_code == 200:
                    return {'status': 'success', 'message': 'Attendance marked successfully'}
                else:
                    return {'status': 'error', 'message': f'Failed to submit attendance: {submit_response.status_code}'}
            
            # Fallback error
            return {'status': 'error', 'message': 'Unknown error during attendance marking'}
            
        except Exception as e:
            logger.error(f"Error marking attendance: {str(e)}")
            return {'status': 'error', 'message': str(e)}
