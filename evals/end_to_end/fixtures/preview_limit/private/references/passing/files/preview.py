def preview(text, limit=20):
    if limit < 0:
        raise ValueError('limit must be nonnegative')
    if len(text) <= limit:
        return text
    return text[:limit] if limit < 3 else text[:limit - 3] + '...'
