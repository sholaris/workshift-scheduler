from datetime import datetime
from os import path
import pickle
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

class Scheduler:
    def __init__(self, sheet_name, person, version='v1'):
        self.version = version
        self.sheet_name = sheet_name
        self.person = '.'.join([person.split(' ')[0][0], self.remove_accents(person.split(' ')[1]).capitalize()])
        self.days_mapper = {
            0: ['A', 'B'], 
            1: ['C', 'D'], 
            2: ['E', 'F'], 
            3: ['G', 'H'], 
            4: ['I', 'J'], 
            5: ['K', 'L'], 
            6: ['M', 'N']}
    
    @staticmethod
    def remove_accents(text: str):
        '''  Replace latin polish letters with accents with common ones'''
        letter_mapper = {'ś': 's', 'ą': 'a', 'ć': 'c', 'ę': 'e', 'ó': 'o', 'ł': 'l', 'ń': 'n', 'ź': 'z', 'ż': 'z'}
        text = text.lower()
        for letter in letter_mapper.keys():
            if letter in text:
                text = text.replace(letter, letter_mapper[letter])
        return text

    def clean_record(self, value: str):
        ''' Clean values to extract first and last name in specific format '''
        value = value.replace(' ', '').replace('PLAKATY', '')
        if len(value) > 1:
            if '/' in value:
                value = value.split('/')[1]
            fname, lname = value.split('.')
            lname = self.remove_accents(lname)
            return '.'.join([fname, lname.capitalize()])
        return value

    def load_sheet(self):
        ''' Authorize service account using credential from JSON file and open spredsheet of given title '''
        print(f'Loading "{self.sheet_name}" from Google Sheets...')
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        credentials = ServiceAccountCredentials.from_json_keyfile_name("cred.json", scopes)
        file = gspread.authorize(credentials)
        sheet = file.open(self.sheet_name)
        return sheet

    @staticmethod
    def get_cred():
        ''' Get credentials to Google Calendar API from JSON file. If doesn exists open a console with link to authorization page '''
        credentials = None
        if path.exists('token.pkl'):
            credentials = pickle.load(open("token.pkl", "rb"))
        else:
            scopes = [
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/calendar.events"
                ]

            flow = InstalledAppFlow.from_client_secrets_file(
                "client_secret.json", scopes)

            credentials = flow.run_console()

            pickle.dump(credentials, open("token.pkl", "wb"))

        return credentials

    def api_build(self):
        ''' Build a Google Calendar API Resource to interact with '''
        print('Building Google Calendar API Resource...')
        credentials = self.get_cred()
        service = build('calendar', 'v3', credentials=credentials)
        self.GOOGLE_CALENDAR_API = service
 
    @staticmethod
    def create_event(
            title: str,
            location: str,
            startDate: str,
            endDate: str):
        ''' Return dictionary representing Google Calendar Event object'''
        return {
            'summary': title, 
            'location': location, 
            'start': {
                'dateTime': startDate, 
                "timeZone": "Europe/Warsaw",
                }, 
            'end': {
                'dateTime': endDate, 
                "timeZone": "Europe/Warsaw",
                }, 
            'reminders': {
                'useDefault': False, 
                'overrides': [
                    {"method": "popup", 'minutes': 15}
                    ], 
                }
            }

# First version of helper functions (less error prone)
    def get_dates(self):
        ''' Return list of dates from the worksheet converted to "YYYY-mm-dd" format '''
        print('Extracting dates...')
        raw_dates = self.sheet.values_get('PT-CZW')['values'][4]
        raw_dates = list(filter(lambda date: len(date) > 0, raw_dates))
        dates = []
        for date in raw_dates:
            date = date.split(' ')
            date.append(str(datetime.now().date().year))
            date = '-'.join(date)
            date = datetime.strptime(date, "%d-%b-%Y").date()
            date = date.strftime("%Y-%m-%d")
            dates.append(date)
        return dates

    def get_hours(self):
        ''' Return list of lists of start and end hours from worksheet converted to datetime format '''
        print('Extracting hours...')
        hours = []
        for values in self.days_mapper.values():
            range1 = values[0] + '7:' + values[0] + '15'
            range2 = values[0] + '24:' + values[0] + '31'
            customer_service = [list(map(lambda hour: datetime.strptime(hour + ':00', '%H:%M:%S').time(), hour[:11].replace(" ", "").replace(
                ".", ":").replace('24', '00').split('-'))) for sublist in self.sheet.values_get(range1)['values'] for hour in sublist]
            ticket_agent = [list(map(lambda hour: datetime.strptime(hour + ":00", '%H:%M:%S').time(), hour[:11].replace(" ", "").replace(
                ".", ":").replace('24', '00').split('-'))) for sublist in self.sheet.values_get(range2)['values'] for hour in sublist]
            hours.append(customer_service + ticket_agent)
        return hours

    def get_workshifts(self):
        ''' Return list of dicts representing particular shift including date and hours '''
        print(f'Extracting "{self.person}" workshifts...')
        workshifts = []
        for key, value in self.days_mapper.items():
            shift = {}
            range1 = value[-1] + '7:' + value[-1] + '15'
            range2 = value[-1] + '24:' + value[-1] + '31'
            customer_service = [self.clean_record(name) for sublist in self.sheet.values_get(range1)['values'] for name in sublist]  # flatten the list of names
            ticket_agent = [self.clean_record(name) for sublist in self.sheet.values_get(range2)['values'] for name in sublist] # flatten the list of names
            employees = customer_service + ticket_agent
            if self.person in employees:
                shift['date'] = self.dates[key]
                shift['hours'] = self.hours[key][employees.index(self.person)]
                workshifts.append(shift)
        return workshifts

    def add_event(self, shift):
        ''' Insert event to the calendar with use of Google Calendar API '''
        print('Adding event...')
        title = 'Praca'
        location = 'Kino Nowe Horyzonty Kazimierza Wielkiego 19, 50-077 Wrocław, Polska'
        
        start = shift['date'] + 'T' + shift['hours'][0].strftime('%H:%M:%S')
        if shift['hours'][1].hour == 0:
            shift['date'] = shift['date'][:-2] + str(int(shift['date'][-2:]) + 1)

        end = shift['date'] + 'T' + shift['hours'][1].strftime('%H:%M:%S')
        event = self.create_event(title, location, start, end)
        try:
            self.GOOGLE_CALENDAR_API.events().insert(calendarId='primary', body=event).execute()
        except HttpError as error:
            print('An error occurred: ', error)
  
# Second version of helper functions (more error prone)
    def get_workshifts_v2(self):
        ''' Return list of cell objects matching given value including row number and column number '''
        print('Extracting workshifts...')
        normal = self.sheet.findall('K. Styś')
        outlier = [self.sheet.find('K. Styś PLAKATY')]
        workshifts = outlier + normal if outlier else normal 
        return workshifts

    def get_hours_v2(self):
        ''' Return list of hours corresponding to cells representing workshifts'''
        print('Extracting hours...')
        hours = []
        for cell in self.workshifts:
            hours.append(self.sheet.cell(cell.row, cell.col-1).value[:11].replace(' ', '').replace('.',':').replace('24', '00'))
        hours = [hour.split('-') for hour in hours]
        hours = [[datetime.strptime(item+':00', '%H:%M:%S').time().strftime('%H:%M:%S') for item in hour] for hour in hours]
        return hours

    def get_dates_v2(self):
        ''' Return list of dates corresponding to cells representing workshifts'''
        print('Extracting dates...')
        days = []
        for cell in self.workshifts:
            days.append(self.sheet.cell(5, cell.col-1).value)
        days = [day + ' ' + str(datetime.now().date().year) for day in days]
        days = [datetime.strptime(day, '%d %b %Y').date().strftime('%Y-%m-%d') for day in days]
        return days

    def add_event_v2(self, date: str, hours: list):
        ''' Insert event to the calendar with use of Google Calendar API '''
        print('Adding event...')
        title = 'Praca'
        location = 'Kino Nowe Horyzonty Kazimierza Wielkiego 19, 50-077 Wrocław, Polska'

        start = date + 'T' + hours[0]
        if hours[1][:2] == '00':
            date = date[:-2] + str(int(date[-2:]) + 1)    
        end = date + 'T' + hours[1]
        event = self.create_event(title, location, start, end)

        try:
            self.GOOGLE_CALENDAR_API.events().insert(calendarId='primary', body=event).execute()
        except HttpError as error:
            print('An error occurred: ', error)

    def execute(self):
        self.api_build()    
        if self.version == 'v2':
            self.sheet = self.load_sheet().worksheet('PT-CZW')
            self.workshifts = self.get_workshifts_v2()
            self.hours = self.get_hours_v2()
            self.dates = self.get_dates_v2()
            for i in range(len(self.workshifts)):
                self.add_event_v2(self.dates[i], self.hours[i])
        else:
            self.sheet = self.load_sheet()
            self.hours = self.get_hours()
            self.dates = self.get_dates()
            self.workshifts = self.get_workshifts()
            for event in self.workshifts:
                self.add_event(event)
        
        print('Events successfuly added!')
    