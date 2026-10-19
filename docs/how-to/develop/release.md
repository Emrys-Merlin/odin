# Release

**How-to guide** — steps for one task you already know you want to do.

How a merge becomes a release, and which label to set. There is no manual release step: every
merge to `main` is released by `.github/workflows/release.yml`. Your only decision is the PR's
`release:*` label.

The rules — which label means which bump, never tagging by hand — are in the "Release" section
of [`CLAUDE.md`](https://github.com/Emrys-Merlin/odin/blob/main/CLAUDE.md#release); this page
shows how to apply them.

## 1. Label the PR

Set **at most one** `release:*` label on the PR, as listed in `CLAUDE.md`:

- No label for a normal change (new feature, behaviour change): a minor release.
- `release:patch` for a hotfix.
- `release:none` when nothing in the image changes: docs, CI, tests only.
- `release:major` only to go live (`1.0.0`) or, after that, for a breaking change.

The **Release label** check (`.github/workflows/release-label.yml`) fails the PR when it carries
two `release:*` labels or an unknown one. Labels can change until the merge; the release reads
them afterwards.

## 2. Merge

Merge the PR once CI is green. On the push to `main`, the **Release** workflow:

1. Recreates the three `release:*` labels, in case someone deleted one.
2. Plans the release with `scripts/release_plan.py`: it takes every commit on `main` since the
   latest `vX.Y.Z` tag, looks up the label of the PR each came from (a commit without a PR counts
   as minor) and applies the largest bump. Without any tag the first release is `v0.1.0`. Only
   `release:none` commits: nothing is released and the workflow stops after the build.
3. Builds the image with podman, passing the version as a build argument, and smoke-tests it:
   `odin --version` in the image must print exactly that version.
4. Pushes the tag `vX.Y.Z`.
5. Pushes the image to `ghcr.io/emrys-merlin/odin` as `X.Y.Z`, `X.Y`, `X`, `latest` and the
   commit SHA.
6. Creates the GitHub Release `vX.Y.Z` with the image, its digest and generated release notes.

The tag is the only source of the version: `pyproject.toml` has no version, and the package
derives it from the latest tag (hatch-vcs). So never create a `v*` tag or set a version by hand.

On a PR the same workflow only builds and smoke-tests the image, with a dev version
`0.0.0+g<sha>` that is never published.

## 3. Check the release

- The **Actions** tab shows the Release run on `main`; its "Plan release" step logs the label it
  found for each commit and the version (`v0.11.0 -> v0.12.0`).
- The release is listed under **Releases** on GitHub, the image under **Packages**.
- `podman run --rm ghcr.io/emrys-merlin/odin:X.Y.Z --version` prints `X.Y.Z`.

The homelab follows the major tag, so `podman auto-update` picks up minor and patch releases on
its own; [Upgrade](../operate/upgrade.md) covers the rest, including a major bump.

### If the Release run failed

Fix the cause, then re-run the failed run from the Actions tab. A re-run is safe: if the commit
already carries the tag, the plan reuses that version, and an existing GitHub Release is left
alone. Two merges in quick succession are also safe: release runs on `main` never overlap, and a
commit whose run was skipped is folded into the next release with its label.

## Change a workflow from a cloud session

Cloud sessions cannot push changes under `.github/workflows/` (the GitHub connection lacks the
`workflow` scope). The procedure is in the "Environment" section of
[`CLAUDE.md`](https://github.com/Emrys-Merlin/odin/blob/main/CLAUDE.md#environment); in commands:

```sh
# 1. The workflow change as its own commit(s), nothing else in them
git add .github/workflows/
git commit -m "CI: …"

# 2. Export it to a patch file
git format-patch -1 HEAD -o /tmp/    # -N for the last N commits

# 3. Drop the commit(s) before pushing the rest
git reset --hard HEAD~1
git push -u origin <branch>
```

Send the `.patch` file in the session and paste it into the PR description, so it survives the
container, and say in the PR that it needs the patch. Tim applies it to the PR branch locally:

```sh
git switch <branch>
git am < 0001-CI-….patch
git push
```

Make the workflow commit(s) the last on the branch, so step 3 drops nothing else.
