def preview(text, limit=20):
    return text if len(text) <= limit else text[:limit] + '...'
