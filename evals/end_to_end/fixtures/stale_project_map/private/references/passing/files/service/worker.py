from service.errors import TemporaryFailure
from service.policy import MAX_ATTEMPTS


def run_job(operation):
    for attempt in range(MAX_ATTEMPTS):
        try:
            return operation()
        except TemporaryFailure:
            if attempt + 1 == MAX_ATTEMPTS:
                raise
