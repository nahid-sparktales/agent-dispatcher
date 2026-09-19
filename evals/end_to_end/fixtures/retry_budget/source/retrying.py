class TransientError(Exception):
    pass

def retry_call(operation, attempts=3):
    for _ in range(attempts + 1):
        try:
            return operation()
        except Exception:
            continue
    return None
