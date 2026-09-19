# Catalog migration requirements
The current local desktop tool reads catalog.csv with sku,name,price_cents headers.
SKUs are case-sensitive nonempty strings. price_cents is an integer >= 0. Reject the
whole import if any row is invalid or if a SKU is duplicated; never silently choose
a duplicate. No concurrent CSV editing is allowed during migration: freeze a copy,
record its checksum, import that copy, and verify the source checksum before cutover.
Keep the original CSV and ship the SQLite read path behind a local setting. A
rollback switches that setting back to CSV. The app must work offline. SQLite is
available in Python's standard library. This task is a plan, not implementation.
