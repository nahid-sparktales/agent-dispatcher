# Session API contract

`session_api.api.handle_request(path, token=None, env=None)` returns a dictionary
with integer `status` and a `body` value. `env` is the supplied environment mapping;
use it directly rather than the machine environment. `/health` is public.
`/profile` requires token `demo-session` unless guest access is explicitly enabled.
Other tokens do not authenticate. Unknown routes return 404.

APP_ALLOW_GUEST defaults to false when absent. Values are case-insensitive and trim
surrounding whitespace: true/1/yes enable; false/0/no disable. Every other provided
value, including an empty string, must raise ValueError while loading settings.
The default-false rule applies only when the key is missing. Do not mutate env.
Do not change the current router or identity responses, or use the archived module.
