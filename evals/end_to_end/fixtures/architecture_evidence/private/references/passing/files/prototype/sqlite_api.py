# Retired prototype, never imported by flowdesk.
import sqlite3

def handle_request(method, path):
    return sqlite3.connect(":memory:").execute("SELECT 1").fetchall()
