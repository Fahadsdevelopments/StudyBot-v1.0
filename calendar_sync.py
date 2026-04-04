import os
import json
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = 'service_account.json'


def get_calendar_service():
    """Get authenticated Google Calendar service using service account"""
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('calendar', 'v3', credentials=credentials)


def get_calendar_id():
    """Get the calendar ID from env or use primary"""
    return os.getenv('GOOGLE_CALENDAR_ID', 'fahadsayyed544@gmail.com')


def add_event(service, title, start_time_str, end_time_str,
              description='', color_id='1'):
    """Add a single event to Google Calendar"""
    today = datetime.now().strftime('%Y-%m-%d')
    calendar_id = get_calendar_id()

    event = {
        'summary': title,
        'description': description,
        'start': {
            'dateTime': f'{today}T{start_time_str}:00',
            'timeZone': 'Europe/Berlin',
        },
        'end': {
            'dateTime': f'{today}T{end_time_str}:00',
            'timeZone': 'Europe/Berlin',
        },
        'colorId': color_id,
    }

    event = service.events().insert(
        calendarId=calendar_id, body=event).execute()
    return event.get('htmlLink')


def push_schedule_to_calendar(schedule_blocks):
    """Push a full schedule to Google Calendar"""
    service = get_calendar_service()

    color_map = {
        'exam': '11',
        'assignment': '5',
        'reading': '2',
        'project': '6',
        'quiz': '3',
        'lab': '4',
        'other': '1',
    }

    links = []
    for block in schedule_blocks:
        title = f"📚 {block['title']}"
        description = (
            f"Type: {block['type']}\n"
            f"Complexity: {block['complexity']}\n"
            f"Duration: {block['duration_hours']}h\n"
            f"Added by StudyBot"
        )
        color = color_map.get(block['type'], '1')

        link = add_event(
            service,
            title=title,
            start_time_str=block['start_time'],
            end_time_str=block['end_time'],
            description=description,
            color_id=color
        )
        links.append({'title': block['title'], 'link': link})
        print(f"Added: {block['title']} at {block['start_time']}")

    return links


if __name__ == "__main__":
    service = get_calendar_service()
    print("✅ Google Calendar connected successfully!")

    link = add_event(
        service,
        title="StudyBot Test Event",
        start_time_str="10:00",
        end_time_str="11:00",
        description="Testing StudyBot calendar integration"
    )
    print(f"✅ Test event created: {link}")