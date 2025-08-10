import datetime

def get_current_datetime() -> str:
    """Returns the current date and time in ISO 8601 format."""
    now = datetime.datetime.now().isoformat()
    print(f"--- [Alice/Get-DateTime] --- : {now}")
    return now

def get_mapping():
    return {
        "time.current_datetime": get_current_datetime,  # Returns the current date and time in ISO 8601 format.
    }