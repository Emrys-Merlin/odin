#!/usr/bin/env bash
# SessionStart hook: prepares Claude Code cloud sessions. No-op on local machines.
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-.}"

# uv tool installs land in ~/.local/bin; it must win over any older uv elsewhere on PATH.
export PATH="$HOME/.local/bin:$PATH"
[ -n "${CLAUDE_ENV_FILE:-}" ] && echo "export PATH=\"$HOME/.local/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"

# The cloud image ships an old uv (0.8.x) that neither knows the final Python 3.14 nor matches
# our uv_build pin. The astral.sh installer and `uv self update` are blocked by the proxy, but
# PyPI works, so install uv as a uv tool from there.
uv_is_current() {
  command -v uv >/dev/null || return 1
  local version
  version="$(uv --version | awk '{print $2}')"
  [ "$(printf '%s\n' 0.12 "$version" | sort -V | head -n1)" = 0.12 ]
}
if ! uv_is_current; then
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
  uv tool install --force 'uv>=0.12'
  hash -r
fi

# Installs the Python from .python-version (final release, not an rc).
uv python install
# An existing venv built on a pre-release Python is not replaced by `uv sync`; rebuild it.
if [ -x .venv/bin/python ] &&
  [ "$(.venv/bin/python -c 'import sys; print(sys.version_info.releaselevel)')" != final ]; then
  rm -rf .venv
fi

[ -f pyproject.toml ] && uv sync
[ -f .pre-commit-config.yaml ] && uv run prek install
exit 0
