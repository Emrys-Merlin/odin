# Health endpoint

**Reference** — exact facts to look up.

`GET /health`: whether ODIN can do its job, for Podman's health check and monitors such as
Uptime Kuma.

`odin run` serves it on all interfaces inside the container, on port `ODIN_HEALTH_PORT` (default
`8081`, `0` turns it off; see [Configuration](configuration.md#environment-variables)). The pod
publishes nothing by default; see [Deployment units](deployment-units.md#odinpod). `odin health`
asks it from inside the container (see [CLI](cli.md)). Why it works this way:
[Reliability](../explanation/reliability.md#health).

## Requests

| Request | Status |
|---|---|
| `GET /health` (a query string is ignored) | `200` when up, `503` when down |
| `/health` with any other method | `405`, with `Allow: GET` |
| any other path | `404` |
| a request that is not HTTP | `400` |
| a request not complete within 5 s | connection closed, no answer |

Answering reads only what the bot recorded; it never calls the Signal API. Every answer is JSON
and closes the connection.

## Body

```json
{
  "status": "down",
  "reasons": ["announcement for week 2026-10-25 unsent for 40 min (SignalApiError)"],
  "warnings": [],
  "setup_pending": false,
  "version": "0.9.0"
}
```

| Field | Type | Meaning |
|---|---|---|
| `status` | string | `up` (HTTP 200) or `down` (HTTP 503). Down exactly when `reasons` is not empty. |
| `reasons` | list of strings | Why ODIN is down, see [Reasons](#reasons). |
| `warnings` | list of strings | Problems that leave the status `up`, see [Warnings](#warnings). |
| `setup_pending` | boolean | `true` while ODIN only waits for `odin setup`: not set up, a wizard running, or the number not registered. `odin health --setup-ok` counts that as healthy. |
| `version` | string | The running ODIN version. |

The body holds no personal data: no phone numbers, group IDs, names or message texts — only step
names, dates, durations and error class names.

## Reasons

Durations are whole minutes, rounded down. `<step>` is one of `flat_ask`, `nudge`,
`announcement`, `cancellation`, `tally`, `flat_ask_retry`, `announcement_notice`; `<week>` is the
dinner date of the week (`2026-10-25`).

| Reason | Down when |
|---|---|
| `starting` | ODIN has just started: it has not yet checked whether it is set up, or the bot has not finished its first reconcile tick. |
| `not ready: <why>` | `odin run` waits. `<why>` is the reason it logs: `no flat group chosen` (or dinner, or both), `odin setup is running`, `SIGNAL_NUMBER is not registered with the Signal API` (all `setup_pending`), or `the Signal API is not reachable`. |
| `last reconcile tick finished <n> min ago` | No tick has finished for more than 3 tick intervals (3 min), and no tick is in progress for less than that. |
| `no reconcile tick finished since the bot started <n> min ago` | The same, before the first tick. |
| `<step> for week <week> unsent for <n> min (<Error>)` | Sending the step has failed for more than 15 minutes, counted from its first failed attempt. `<Error>` is the class of the latest error, e.g. `SignalApiError`, `ConnectError`, `ReadTimeout`. Gone as soon as the step is sent or recorded as skipped. |
| `Signal event connection not up yet` | The bot's WebSocket to the Signal API has not been up since the bot started. |
| `Signal event connection down for <n> min` | The WebSocket has been down for more than 2 minutes; reactions are missed meanwhile. |

While `not ready` is the reason, it is the only one.

## Warnings

| Warning | When |
|---|---|
| `<step> for week <week> sent, but its reactions cannot be counted` | The flat poll (`flat_ask`) or the announcement of the current week went out, but Signal's answer could not be read, so ODIN cannot count the 👍 on it. The flat group was told (see [Reliability](../explanation/reliability.md#unreadable-send-responses)). Not shown for a cancelled week, nor for the flat poll once a retry is tracked. |
