# Change the groups

**How-to guide** — steps for one task you already know you want to do.

Point ODIN at another flat or dinner group.

!!! note "Assumed setup"

    Commands run as the `odin` user (`sudo machinectl shell odin@`), with files where
    [First deployment](../../tutorials/first-deployment.md) puts them: see
    [Host layout](../../reference/deployment-units.md#host-layout). Adjust the paths if your
    setup differs.

## Pick a good moment

Switch between the week's tally and the next flat ask (with the default schedule: Friday
afternoon to Tuesday evening). Then the week is finished and the next one starts in the new
groups.

Switching mid-week also works if ODIN stays in the old group(s) until the week is over:

- Messages ODIN already sent keep counting reactions **from the group they went to**: a 👍 on this
  week's flat ask in the old flat group still confirms dinner, and the tally still counts the
  announcement in the old dinner group. See [Reactions](../../explanation/reactions.md#the-rules).
- Everything ODIN sends after the switch goes to the new groups: the nudge, the decision, the
  tally, command replies and a confirmed `/introduce`.
- Chat commands are answered only in the current flat group, so tell the flatmates where to write.

## Choose other groups

1. On your phone, add Odin 🍽️ to the new group(s): group settings → *Add members* → Odin 🍽️.
   ODIN does not need to be an admin. Do not remove it from the old group yet.
2. Run the group step of the wizard again:

    ```bash
    podman exec -it odin odin setup --redo groups
    ```

    It lists the groups ODIN sees, e.g.

    ```text
    Groups ODIN sees:
      1. Sonntagsessen — member
      2. WG — member
      3. WG neu — member
    ```

3. When the groups you want show as **member**, press Enter at *Are both groups listed as
   member?*, then type the number of the flat group and of the dinner group. They must be two
   different groups. The wizard always asks for both:

    - **Only one group changes:** pick the unchanged group again for its role.
    - **Swap flat and dinner group:** pick each group for the other role.

4. Optional, to see that ODIN can write to the new flat group:

    ```bash
    podman exec -it odin odin setup --redo test
    ```

5. Optional, for a new dinner group: let ODIN introduce itself there, see
   [Introduce ODIN to the dinner group](../chat/introduce-odin.md).

The running bot pauses while the wizard runs and picks up the new groups by itself within 30 s;
no restart needed. The new IDs are stored in ODIN's database.

## Check the switch

```bash
podman exec odin odin setup --status
```

shows both groups with their names, e.g. `✓ Flat group: group.… (from database) — WG neu`. A
group marked `ODIN is not in this group` or `ODIN is only invited` needs fixing (see below). The
log (`journalctl --user -u odin -e`) shows `setup changed (new groups); pausing the bot`, then
the groups it runs with.

If a group shows `(from env var)`, `FLAT_GROUP_ID` / `DINNER_GROUP_ID` is set and overrides your
choice: see [Override the groups with env vars](#override-the-groups-with-env-vars).

## Leave the old group

Once the week that started in the old group is over (its tally has gone out, or its dinner was
cancelled), remove Odin 🍽️ from the old group on your phone: group settings → Odin 🍽️ →
*Remove from group*. Before that, reactions in the old group would be lost. Skip this step for a
group that keeps a role, e.g. after a swap.

## ODIN shows as "INVITED, not a member"

ODIN lacks the profile key of whoever added it. That person opens ODIN's message request,
accepts it and replies. If you added it yourself, do the hello again — with another operator
number, if someone else is adding ODIN:

```bash
podman exec -it odin odin setup --redo hello --redo groups
```

If ODIN stays invited, remove it from the group and add it again.

## Look up group IDs

```bash
podman exec odin odin list-groups
```

prints every group ODIN is in, with its ID. `podman exec odin odin setup --status` and
`podman exec odin odin check-config` show the chosen groups and where each ID comes from
(`database` or `env var`).

## Override the groups with env vars

For special cases only, e.g. testing against another group without touching the database:

1. In `~/odin/odin.env`, set the IDs (the `group.…` form `list-groups` prints):

    ```ini
    FLAT_GROUP_ID=group.XXXXXXXX
    DINNER_GROUP_ID=group.XXXXXXXX
    ```

    While set, they take precedence over the database; one alone overrides just that group.

2. `systemctl --user restart odin`.
3. Check with `podman exec odin odin check-config`: the group shows `(from env var)`.

To go back to the stored groups, comment the lines out again and restart. The variables are
listed in [Configuration](../../reference/configuration.md).
