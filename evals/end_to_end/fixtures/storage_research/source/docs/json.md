# JSON option
Python includes json. JSON is human-readable and simple for whole-file loading.
json itself provides no transaction manager, uniqueness enforcement, or index.
A robust design would need an atomic temporary-file replacement protocol and careful
error handling; multi-record invariants must be implemented by the application.
This note supplies no benchmark or crash-safety guarantee for naive direct writes.
