from datetime import datetime
from zoneinfo import ZoneInfo

def convert_display_time(timestamp):
    return datetime.fromisoformat(timestamp).astimezone(ZoneInfo('America/New_York')).isoformat()
