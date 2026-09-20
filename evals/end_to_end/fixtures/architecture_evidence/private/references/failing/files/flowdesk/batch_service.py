class TaskService:
    def __init__(self, store):
        self.store = store

    def list_tasks(self):
        return self.store.list_tasks()

    def add_task(self, title):
        return self.store.add_task(title)
