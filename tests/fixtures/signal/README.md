# Signal API fixtures

Response and WebSocket message shapes of signal-cli-rest-api (`MODE=json-rpc`) used by the
parsing and REST client tests. Phone numbers, UUIDs and group IDs are made up.

**Not recorded from real Signal.** Cloud sessions cannot reach Signal, so these files were built
by hand from the sources of signal-cli-rest-api (`src/api/api.go`, `src/client/client.go`,
`src/client/jsonrpc2.go`) and signal-cli (`RegisterCommand`, `VerifyCommand`, `CommandUtil`,
`RegistrationManagerImpl`, `SignalJsonRpcCommandHandler`), as of 2026-10. Check them against
real responses when the bot is registered and fix the files (and the matching code) where they
differ:

- `errors.json` — error responses of the admin endpoints (all HTTP 400 with
  `{"error": "<message>"}`, plus a 429 and a non-JSON body). Each `case` has a test in
  `tests/test_signal_errors.py`. The full messages are guesses around the substrings ODIN
  matches on; only the substrings matter.
- `about.json`, `accounts.json` — `GET /v1/about`, `GET /v1/accounts`.
- `direct_message.json` — a direct (non-group) text message as received on `/v1/receive`.
- `groups.json` — the third group (`Buchclub`, `"member": false`) is one ODIN is only invited to.
