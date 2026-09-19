class Cache:
    def __init__(self, now):
        self.now = now
        self.entries = {}

    def put(self, key, value, ttl):
        self.entries[key] = (self.now() + ttl, value)

    def get(self, key, default=None):
        if key not in self.entries:
            return default
        expiry, value = self.entries[key]
        if self.now() > expiry:
            del self.entries[key]
            return default
        return value or default
