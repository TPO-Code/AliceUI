import json
from typing import Any, Optional

import requests

from ._base import CALENDAR_BASE

def create_calendar_event(title: str, start_time: str, end_time: str, description: Optional[str] = None, event_type: str = "event") -> str:
    """Creates a new event or alarm in the calendar."""
    # ... (implementation is unchanged)
    print(f"--- [Alice/Create-Event] --- : {title}")
    url = f"{CALENDAR_BASE}/api/events/"
    payload = {k: v for k, v in locals().items() if k != 'url' and v is not None}
    payload["is_notified"] = False
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return json.dumps(response.json())
    except requests.exceptions.RequestException as e: return json.dumps({"error": f"API request failed: {e}"})

def find_events_by_time_range(start_time: str, end_time: str) -> str:
    """Finds calendar events within a specific time range."""
    # ... (implementation is unchanged)
    print(f"--- [Alice/Find-Event-Time] --- : {start_time} to {end_time}")
    url = f"{CALENDAR_BASE}/api/events/"
    params = {"start": start_time, "end": end_time}
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return json.dumps(response.json())
    except requests.exceptions.RequestException as e: return json.dumps([{"error": f"API request failed: {e}"}])

def search_events_by_keyword(keyword: str) -> str:
    """Searches for calendar events by a keyword in their title or description."""
    # ... (implementation is unchanged)
    print(f"--- [Alice/Find-Event-Keyword] --- : {keyword}")
    url = f"{CALENDAR_BASE}/api/events/search/"
    params = {"keyword": keyword}
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return json.dumps(response.json())
    except requests.exceptions.RequestException as e: return json.dumps([{"error": f"API request failed: {e}"}])

def edit_calendar_event(event_id: int, **kwargs: Any) -> str:
    """Updates an existing event or alarm in the calendar."""
    # ... (implementation is unchanged)
    print(f"--- [Alice/Edit-Event] --- : {event_id}")
    url = f"{CALENDAR_BASE}/api/events/{event_id}"
    if not kwargs: return json.dumps({"error": "No fields provided to update."})
    try:
        response = requests.put(url, json=kwargs)
        response.raise_for_status()
        return json.dumps(response.json())
    except requests.exceptions.RequestException as e:
        error_msg = f"API request failed: {e}"
        if e.response and e.response.status_code == 404: error_msg = f"Event with ID {event_id} not found."
        return json.dumps({"error": error_msg})

def remove_calendar_event(event_id: int) -> str:
    """Deletes an event or alarm from the calendar using its unique ID."""
    # ... (implementation is unchanged)
    print(f"--- [Alice/Remove-Event] --- : {event_id}")
    url = f"{CALENDAR_BASE}/api/events/{event_id}"
    try:
        response = requests.delete(url)
        response.raise_for_status()
        return json.dumps(response.json())
    except requests.exceptions.RequestException as e:
        error_msg = f"API request failed: {e}"
        if e.response and e.response.status_code == 404: error_msg = f"Event with ID {event_id} not found."
        return json.dumps({"error": error_msg})

def get_mapping():
    return {
        # Manages scheduling, reminders, and events.
        "calendar.create_event": create_calendar_event,  # Creates a new event or alarm in the calendar.
        "calendar.edit_event": edit_calendar_event,  # Updates an existing event using its unique ID.
        "calendar.find_events_by_time_range": find_events_by_time_range,
        # Finds all calendar events within a specific time range.
        "calendar.remove_event": remove_calendar_event,  # Deletes an event from the calendar using its ID.
        "calendar.search_events_by_keyword": search_events_by_keyword,
        # Searches for events by a keyword in the title or description.
    }

