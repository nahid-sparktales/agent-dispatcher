class MemoryTaskStore:
    def __init__(self):
        self._rows = []

    def list_tasks(self):
        return [dict(row) for row in self._rows]

    def add_task(self, title):
        row = {"id": len(self._rows) + 1, "title": title}
        self._rows.append(row)
        return dict(row)
