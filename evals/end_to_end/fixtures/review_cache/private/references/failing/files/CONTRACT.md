# Cache contract
The caller supplies a clock returning numeric seconds. Entries are expired exactly
when now >= expiry. A missing or expired key returns default. A live entry returns
its value, even if that value is False, 0, an empty string, or None. TTL values are
nonnegative. No persistence or concurrency requirements are part of this task.
