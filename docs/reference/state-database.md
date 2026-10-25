# State database

**Reference** — exact facts to look up.

The SQLite file at `ODIN_DB` (see [Configuration](configuration.md#environment-variables); the
container image uses `/data/odin.db`) holds everything ODIN learns while running. Code:
`src/odin/store.py`. Why ODIN records what it does: [Reliability](../explanation/reliability.md).

!!! warning "Read, don't write"
    Opening the file with `sqlite3` to look is safe while ODIN runs. Changing rows by hand is not
    supported: stop ODIN and take a [backup](../how-to/operate/backup-restore.md) first, or use
    the chat commands and `odin setup`, which write the same rows.

## Conventions

| What | Stored as |
|---|---|
| Dinner week | `TEXT`, the ISO date of its dinner (`2026-10-25`). A week runs until its dinner starts; from then on it is the next week. |
| Day | `TEXT`, ISO date (`2026-12-27`). |
| Moment | `TEXT`, ISO 8601 in UTC (`2026-10-20T16:00:00+00:00`), so text order is time order. |
| Signal message | Its author (phone number or UUID, as Signal reports it) and its Signal timestamp in milliseconds (`INTEGER`). Reactions refer to messages this way. |
| Person who made a change | `TEXT`: the sender's Signal name if known, else their number. |
| Enumerations | `TEXT`, one of the values listed with the column. |

Foreign keys are on (`PRAGMA foreign_keys = ON`); the only one is from `reactions` to
`messages`.

## Schema version

The schema version is `PRAGMA user_version`; the current one is **10**. Every `odin` command that
opens the database applies the migrations from the stored version up to its own, each in one
transaction; a new file starts at `0` and is migrated all the way. Migrations are only ever
appended, never changed.

A database whose version is newer than the code supports is refused with
`database schema version N is newer than supported (M)`. This is what stops an older image after
a [rollback](../how-to/operate/rollback.md) past a schema change.

| Version | Change |
|---|---|
| 1 | `actions`, `messages`, `reactions` |
| 2 | `actions.outcome` |
| 3 | `settings` |
| 4 | `overrides` |
| 5 | `overrides.after_week` |
| 6 | `dropped_weeks` |
| 7 | `applied_dinner` |
| 8 | `skip_dates` |
| 9 | `introductions` |
| 10 | `hiatuses` |

## Tables

### `actions`

One row per step of the weekly cycle that was done for a dinner week, so it is never done twice.
Key: (`week`, `action`).

| Column | Type | Null | Meaning |
|---|---|---|---|
| `week` | `TEXT` | no | Dinner week. |
| `action` | `TEXT` | no | The step, see below. |
| `performed_at` | `TEXT` | no | Moment it was sent or skipped. |
| `outcome` | `TEXT` | no | `sent`; `skipped` (deliberately not sent: too late, or not needed, e.g. no nudge); or `silenced` (only `cancellation`: not sent because the cancellation is switched off, see `decision.cancellation`). Default `sent`. |

`action` values:

| Value | Step |
|---|---|
| `flat_ask` | The question to the flat group whether dinner takes place. |
| `nudge` | The reminder to the flat group before the deadline. |
| `announcement` | The invitation to the dinner group. |
| `cancellation` | The cancellation to the flat group. |
| `tally` | The guest count to the flat group; the last step of every week. |
| `flat_ask_retry` | The flat ask went out but could not be tracked; asked again, and this message is the week's flat poll. |
| `announcement_notice` | The announcement went out but could not be tracked; the flat group was told to count by hand. |

`introduction` and `hiatus_notice` are names of steps too (in logs and `/health`), but they are
never rows here: they are recorded in [`introductions`](#introductions) and
[`hiatuses`](#hiatuses).

### `messages`

Messages ODIN sent whose reactions matter. Key: (`week`, `kind`), so a week has at most one
message of each kind; (`author`, `timestamp`) is unique too.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `week` | `TEXT` | no | Dinner week the message belongs to. |
| `kind` | `TEXT` | no | What the message is, see below. |
| `group_id` | `TEXT` | no | The group it was sent to (`group.…`). |
| `author` | `TEXT` | no | ODIN's own number, as Signal reports it. |
| `timestamp` | `INTEGER` | no | Signal timestamp of the message, in milliseconds. |

`kind` values:

| Value | Message |
|---|---|
| `flat_poll` | The flat ask (or its retry); a reaction confirms dinner. |
| `dinner_announcement` | The invitation; reactions are the guests. |
| `cancel_request` | ODIN's reply to `/cancel`; a reaction confirms it. |
| `introduction_request` | ODIN's reply to `/introduce`; a reaction confirms it. Only the latest one counts. |
| `hiatus_request` | ODIN's reply to `/hiatus`; a reaction confirms it. Deleted once the hiatus takes effect. |

Deleting a row deletes its reactions.

### `reactions`

The current reaction of each person on a tracked message. Signal allows one reaction per person,
so a new one replaces the old one; a removed reaction deletes the row. Key: (`msg_author`,
`msg_timestamp`, `reactor`).

| Column | Type | Null | Meaning |
|---|---|---|---|
| `msg_author` | `TEXT` | no | `messages.author` of the message reacted to. |
| `msg_timestamp` | `INTEGER` | no | `messages.timestamp` of the message reacted to. |
| `reactor` | `TEXT` | no | Who reacted (number or UUID). |
| `emoji` | `TEXT` | no | The emoji. |
| `received_at` | `TEXT` | no | Moment the reaction arrived. |

(`msg_author`, `msg_timestamp`) references `messages` (`author`, `timestamp`), `ON DELETE
CASCADE`.

### `settings`

Values chosen in `odin setup`, and the setup lock. Key: `key`.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `key` | `TEXT` | no | See below. |
| `value` | `TEXT` | no | See below. |

| Key | Value |
|---|---|
| `flat_group_id` | The flat group's ID (`group.…`). `FLAT_GROUP_ID` overrides it. |
| `dinner_group_id` | The dinner group's ID. `DINNER_GROUP_ID` overrides it. |
| `setup.operator_number` | The operator's number, to which the hello step sent its direct message. |
| `setup.code_requested_at` | Moment the registration code was requested. |
| `setup.pin_set_at` | Moment the registration lock PIN was set. |
| `setup.profile_applied_at` | Moment the profile (name, avatar, about text) was last applied. |
| `setup.hello_reply_at` | Moment the operator answered the hello message. |
| `setup.test_answered_at` | Moment the test step was answered, whether or not a test message was posted. |
| `setup_lock` | `<token> <heartbeat moment>`, while `odin setup` runs; `odin run` waits meanwhile. A heartbeat older than 2 minutes is stale. |

The `odin setup` steps are described in the [CLI reference](cli.md).

### `overrides`

Config values changed from the chat; they win over the config file until reset. Key: `key`.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `key` | `TEXT` | no | The config value, see below. |
| `value` | `TEXT` | no | The new value, as text. |
| `changed_by` | `TEXT` | no | Who changed it. |
| `changed_at` | `TEXT` | no | Moment of the change. |
| `after_week` | `TEXT` | yes | Only for `schedule.dinner.next`: the dinner week whose dinner it waits for. |

| Key | Value |
|---|---|
| `templates.<name>` | The template text, for each chat-editable template (see [Templates](templates.md)). |
| `schedule.<point>` | `<weekday> <HH:MM>`, e.g. `wed 18:00`, for each schedule point (see [Configuration](configuration.md)). |
| `schedule.nudge.enabled` | `true` or `false`. |
| `decision.cancellation.enabled` | `true` or `false`; `decision.cancellation` (see [Configuration](configuration.md#decision)). |
| `schedule.dinner.next` | A dinner time on another weekday, as for `schedule.dinner`, waiting for the dinner of `after_week`; then it becomes the `schedule.dinner` override. See [Changing the dinner weekday](../explanation/weekday-change.md). |

### `dropped_weeks`

Dinner weeks cut short by a new dinner weekday; ODIN posts their cancellation. Key: `week`.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `week` | `TEXT` | no | The dropped dinner week. |
| `switch` | `TEXT` | no | Moment the new weekday took effect. |

### `applied_dinner`

The dinner time the dinner weeks are currently run under. At most one row.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | no | Always `1`. |
| `point` | `TEXT` | no | `<weekday> <HH:MM>`, e.g. `sun 18:00`. |
| `held_week` | `TEXT` | yes | Set while a new dinner weekday from the config file waits for this dinner week to end. |

### `skip_dates`

Dinner days without dinner, set with `/skip` and removed with `/unskip`. Key: `day`.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `day` | `TEXT` | no | The dinner day. |
| `added_by` | `TEXT` | no | Who set it. |
| `added_at` | `TEXT` | no | Moment it was set. |

### `introductions`

Introductions posted to the dinner group after a confirmed `/introduce`. They belong to no
dinner week. Key: (`request_author`, `request_timestamp`). There is no foreign key: the request
may no longer be tracked.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `request_author` | `TEXT` | no | Author of the confirmed `/introduce` reply. |
| `request_timestamp` | `INTEGER` | no | Its Signal timestamp, in milliseconds. |
| `sent_at` | `TEXT` | no | Moment the introduction was posted. |

### `hiatuses`

Breaks set with `/hiatus` and ended with `/resume`. A row is created on the request; an
unconfirmed request is replaced by the next one. Key: `id`.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | no | Row ID. |
| `week` | `TEXT` | no | Dinner week of the request; the hiatus starts in it. |
| `requested_by` | `TEXT` | no | Who sent `/hiatus`. |
| `requested_at` | `TEXT` | no | Moment of the request. |
| `started_at` | `TEXT` | yes | Moment it took effect; empty while only requested. |
| `from_day` | `TEXT` | yes | First day covered: dinner weeks with a dinner on or after it have no weekly cycle. |
| `notice` | `TEXT` | yes | The notice to the dinner group: `sent`, `skipped`, or `silenced` (the `hiatus` template is not set and the cancellation is switched off); empty until recorded. |
| `notice_at` | `TEXT` | yes | Moment of the notice. |
| `resumed_by` | `TEXT` | yes | Who sent `/resume`. |
| `resumed_at` | `TEXT` | yes | Moment of `/resume`; empty while the hiatus lasts. |
| `until_day` | `TEXT` | yes | Last day covered; empty while the hiatus lasts. |

A hiatus is active when `started_at` is set and `resumed_at` is empty. `from_day` and
`until_day` need not be dinner days.
