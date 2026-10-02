#!/bin/bash
set -euo pipefail

# Cloud sessions only — a local machine manages its own tools.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Never fail session start over a tooling install problem.
bash "$CLAUDE_PROJECT_DIR/.claude/scripts/setup-video-tools.sh" || true

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$CLAUDE_ENV_FILE"
fi
