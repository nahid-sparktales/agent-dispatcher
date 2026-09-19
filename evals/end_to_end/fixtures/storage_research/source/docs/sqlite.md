# SQLite option
Python includes sqlite3. SQLite supports transactions and UNIQUE constraints.
An index can support SKU lookups. A transaction can roll back a failed batch. Schema
changes require a migration strategy, and callers need to handle database errors.
This note supplies no benchmark and promises no particular latency.
