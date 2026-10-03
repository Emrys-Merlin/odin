#!/usr/bin/env bash
# SessionStart hook: prepares Claude Code cloud sessions. No-op on local machines.
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-.}"

if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  [ -n "${CLAUDE_ENV_FILE:-}" ] && echo "export PATH=\"$HOME/.local/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi

[ -f pyproject.toml ] && uv sync
[ -f .pre-commit-config.yaml ] && uv run prek install
exit 0
