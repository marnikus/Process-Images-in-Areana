#!/bin/bash
# install_hooks.sh — installs git hooks for quality gate
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
HOOK=".git/hooks/pre-push"
echo "Installing pre-push hook -> $HOOK"
cat > "$HOOK" << 'HOOKSH'
#!/bin/bash
# pre-push hook — runs quality gate before push (RULE 16)
# Bypass with: git push --no-verify
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"
if [ -f "tools/pre_push_check.sh" ]; then
  bash tools/pre_push_check.sh
  exit $?
else
  echo "⚠ tools/pre_push_check.sh not found, skipping gate"
  exit 0
fi
HOOKSH
chmod +x "$HOOK"
echo "✅ Hook installed at $HOOK"
echo "It runs: bash tools/pre_push_check.sh"
echo "Bypass: git push --no-verify"
