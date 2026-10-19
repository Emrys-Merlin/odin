# Configuration

**Reference** — exact facts to look up.

Every key of the config file, and the environment variables.

ODIN has two sources of settings:

- **The config file** — a TOML file with the behaviour: schedule, emoji, message texts, profile.
  Its path is `ODIN_CONFIG`.
- **Environment variables** — the deployment values: phone number, Signal API URL, file paths.

The config file is validated at startup (`odin run`, `odin check-config`); any error stops ODIN
with a message naming the key. Unknown keys and unknown sections are errors too.

## Config file

Keys are listed grouped as in [`config.example.toml`](#example-file). Every key except the
templates is optional; a missing key takes its default.

### Top level

| Key | Type | Default | Meaning |
|---|---|---|---|
| `timezone` | string, IANA name | `"Europe/Berlin"` | Timezone of every time in `[schedule]`. |
| `emoji` | string, non-empty | `"👍"` | The reaction that counts: flatmates confirming dinner, guests saying they come, the confirmation of a `/cancel` request. Also the `{emoji}` placeholder. |
| `catch_up_grace` | `"until_dinner"` or integer > 0 | `"until_dinner"` | How late a missed action may still be performed: until the week's dinner starts, or this many minutes after its scheduled time. Later it is skipped. See [Reliability](../explanation/reliability.md). |

### `[schedule]`

The weekly cycle. Each point is an inline table `{ weekday = "…", time = "…" }`; a missing
`weekday` or `time` takes the default of that point.

| Key | Default | Meaning |
|---|---|---|
| `flat_ask` | `tue` `18:00` | The flat group is asked whether dinner takes place. |
| `nudge` | `wed` `12:00`, `enabled = true` | Reminder to the flat group if nobody has confirmed yet. |
| `flat_deadline` | `wed` `18:00` | Confirmations close; the dinner group gets the announcement or the cancellation. |
| `rsvp_by` | `fri` `14:00` | Guests are asked to react by then. Only shown in the texts; nothing happens at this time. |
| `tally` | `fri` `14:00` | The flat group is told how many guests reacted. |
| `cook` | `sun` `17:00` | Optional start for helping to cook. Only shown in the texts. |
| `dinner` | `sun` `18:00` | Dinner starts. Ends the dinner week. |

Fields of a point:

| Field | Type | Values |
|---|---|---|
| `weekday` | string | `mon` … `sun` or `monday` … `sunday`, case-insensitive |
| `time` | string or TOML local time | `"HH:MM"`, 24-hour, whole minutes, in `timezone` |
| `enabled` | boolean | `nudge` only. `false` turns the nudge off; its time is kept. |

All points belong to the week that ends with `dinner`. They must follow this order within the
week leading up to dinner (a point "before" another lies further from dinner):

| Rule | Strict |
|---|---|
| `flat_ask` before `flat_deadline` | yes |
| `flat_ask` before `nudge` before `flat_deadline` (only while the nudge is enabled) | yes |
| `flat_deadline` not after `rsvp_by` | no, may be equal |
| `flat_deadline` before `tally` | yes |
| `tally` before `dinner` | yes |
| `flat_deadline` before `cook` | yes |

A schedule that breaks a rule is rejected with the first broken rule. Changing the `dinner`
weekday while a dinner week is running takes effect at that week's dinner; see
[Changing the dinner weekday](../explanation/weekday-change.md).

### `[profile]`

ODIN's Signal profile. Applied by `odin setup`, not by `odin run`.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `name` | string, non-empty | `"Odin 🍽️"` | Profile name. |
| `avatar` | string, file path | *(none)* | Profile picture, PNG or JPEG. A relative path is resolved against the config file's directory. The file must exist. |
| `about` | string | *(none)* | About text under the name. Not set: Signal's about text is left as it is. `""`: cleared. |

### `[templates]`

The message texts. Every template is **required** and has no default; a missing or empty one is
an error. Leading and trailing whitespace is stripped.

| Key | Sent to | Language | When |
|---|---|---|---|
| `flat_ask` | flat group | German | at `flat_ask` |
| `nudge` | flat group | German | at `nudge`, if nobody has confirmed |
| `cancellation` | dinner group | German, blank line, English | at `flat_deadline` without confirmation, or after a confirmed `/cancel` |
| `announcement` | dinner group | German, blank line, English | at `flat_deadline` with a confirmation |
| `tally` | flat group | German | at `tally`, if dinner is on |
| `hello` | the operator, direct message | German | during `odin setup` |
| `flat_test` | flat group | German | optionally, at the end of `odin setup` |

The placeholders each template may use, and their values, are in
[Templates](templates.md). Unknown placeholders and format specs (`{deadline:>5}`) are rejected
at startup; `{{` and `}}` are literal braces.

### Example file

`config.example.toml` from the repository. Every value in it is the default, except the
templates, which have no defaults.

```toml
--8<-- "config.example.toml"
```

## Environment variables

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `SIGNAL_NUMBER` | yes | — | ODIN's phone number in E.164 format (`+49…`, no spaces). |
| `SIGNAL_API_URL` | no | `http://localhost:8080` | Base URL of signal-cli-rest-api, `http` or `https`. A trailing `/` is dropped. |
| `ODIN_CONFIG` | yes | — | Path to the config file. The container image sets `/config/config.toml`. |
| `ODIN_DB` | yes | — | Path to the SQLite state database. The file is created if missing; its directory must exist. The container image sets `/data/odin.db`. |
| `ODIN_LOG_LEVEL` | no | `INFO` | Log level of the output on stdout: `DEBUG`, `INFO`, `WARNING`, `ERROR` (case-insensitive). |
| `FLAT_GROUP_ID` | no | — | Flat group ID, overriding the one `odin setup` stored. The `group.…` form `odin list-groups` prints. |
| `DINNER_GROUP_ID` | no | — | Dinner group ID, overriding the one `odin setup` stored. Same form. |

An empty or whitespace-only value counts as not set. `odin list-groups` needs only
`SIGNAL_NUMBER` and `SIGNAL_API_URL`. In the [deployment units](deployment-units.md) the
variables come from the env file `~/odin/odin.env`.

## Precedence

| Setting | Wins | Falls back to |
|---|---|---|
| Weekly templates (`flat_ask`, `nudge`, `announcement`, `cancellation`, `tally`) | change via chat (`/settext`) | config file |
| Schedule points and `nudge.enabled` | change via chat (`/settime`, `/nudge`) | config file |
| Group IDs | `FLAT_GROUP_ID` / `DINNER_GROUP_ID` env vars | IDs stored in the database by `odin setup` |

A change via chat is stored in the database and lasts until it is reset (`/resettext`,
`/resettime`); see [Chat commands](chat-commands.md). `timezone`, `emoji`, `catch_up_grace`,
`[profile]`, `hello` and `flat_test` can only be changed in the config file. A changed config
file takes effect when ODIN restarts.
