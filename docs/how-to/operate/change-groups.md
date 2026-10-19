# Change the groups

**How-to guide** — steps for one task you already know you want to do.

Point ODIN at another flat or dinner group.

!!! note "Assumed setup"

    Commands run as the `odin` user (`sudo machinectl shell odin@`), with files where
    [First deployment](../../tutorials/first-deployment.md) puts them: see
    [Host layout](../../reference/deployment-units.md#host-layout). Adjust the paths if your
    setup differs.

## Choose other groups

1. On your phone, add Odin 🍽️ to the new group(s): group settings → *Add members* → Odin 🍽️.
   ODIN does not need to be an admin.
2. Run the group step of the wizard again:

    ```bash
    podman exec -it odin odin setup --redo groups
    ```

    It lists the groups ODIN sees, e.g.

    ```text
    Groups ODIN sees:
      1. Sonntagsessen — member
      2. WG — member
    ```

3. When both groups show as **member**, press Enter at *Are both groups listed as member?*, then
   type the number of the flat group and of the dinner group. They must be two different groups.
4. Optional, to see that ODIN can write to the new flat group:

    ```bash
    podman exec -it odin odin setup --redo test
    ```

The running bot picks up the new groups by itself within 30 s; no restart needed. The new IDs are
stored in ODIN's database.

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
