import datetime
import json
import re


from .calendar_tools import find_events_by_time_range
from .file_tools import find_files
from .time_tools import get_current_datetime


def prepare_for_next_meeting() -> str:
    """
    Finds the user's next calendar event for today and searches for any related notes
    or files in the secure directory to help them prepare.
    """
    print(f"--- [Alice/Composite-MeetingPrep] --- Starting meeting prep.")

    # Step 1: Get the current time and find the range for today's events
    now_iso = get_current_datetime()
    now_dt = datetime.datetime.fromisoformat(now_iso)
    start_of_day = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    end_of_day = now_dt.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()

    print(f"--- [Alice/Composite-MeetingPrep] --- Searching for events between {start_of_day} and {end_of_day}.")

    # Step 2: Find events for today
    events_str = find_events_by_time_range(start_of_day, end_of_day)
    try:
        events = json.loads(events_str)
        if not events or "error" in events[0]:
            return "You have no more meetings scheduled for today."
    except (json.JSONDecodeError, IndexError):
        return "Could not retrieve calendar events or the calendar is empty."

    # Find the next event that hasn't started yet
    next_event = None
    for event in sorted(events, key=lambda x: x['start_time']):
        if datetime.datetime.fromisoformat(event['start_time']) > now_dt:
            next_event = event
            break

    if not next_event:
        return "You have no more meetings scheduled for today."

    title = next_event.get('title', 'Untitled Event')
    start_time_obj = datetime.datetime.fromisoformat(next_event['start_time'])
    formatted_time = start_time_obj.strftime('%I:%M %p')

    print(f"--- [Alice/Composite-MeetingPrep] --- Found next meeting: '{title}' at {formatted_time}.")
    report = f"Your next meeting is '{title}' at {formatted_time}.\n\n"

    # Step 3: Search for related files using keywords from the title
    keywords = re.findall(r'\b\w{3,}\b', title)  # Find words of 3+ letters
    if not keywords:
        report += "Could not extract keywords from the title to search for notes."
        return report

    search_term = keywords[0]  # Use the first significant keyword for simplicity
    print(f"--- [Alice/Composite-MeetingPrep] --- Searching for files related to '{search_term}'.")

    found_files_str = find_files(name_pattern=f"*{search_term}*.*", content_regex=search_term)

    if found_files_str.startswith("No files found"):
        report += "I could not find any files or notes related to this meeting's title."
    else:
        report += f"I found the following potentially related files for you:\n{found_files_str}"

    return report

def get_mapping():
    return {
        "meetings.prepare_for_next": prepare_for_next_meeting,         # Finds the next calendar event and searches for related notes.
    }