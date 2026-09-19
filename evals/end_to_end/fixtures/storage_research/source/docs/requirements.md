# App requirements
One offline desktop process stores up to 20,000 inventory records. It needs atomic
updates across several records, lookup by unique SKU, and recovery after a crash.
Users do not edit storage files directly. There is one writer, and no remote sync.
The implementation must use the Python standard library. No performance benchmark
has been run; choose on correctness and maintainability rather than invented speed.
