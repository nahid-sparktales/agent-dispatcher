from datetime import datetime

def convert_display_time(timestamp):
    return datetime.fromisoformat(timestamp).isoformat()
