class TransientError(Exception):
    pass

def retry_call(operation, attempts=3):
    if attempts <= 0:
        raise ValueError('attempts must be positive')
    for index in range(attempts):
        try:
            return operation()
        except TransientError:
            if index == attempts - 1:
                raise
