#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Print Markdown release notes for a tag, grouped by Conventional Commit type.
# Usage: scripts/release-notes.sh <tag>
set -euo pipefail

tag="${1:?usage: release-notes.sh <tag>}"
previous="$(git describe --tags --abbrev=0 "${tag}^" 2>/dev/null || true)"
range="${previous:+${previous}..}${tag}"

section() {
  local title="$1" type="$2" lines
  lines="$(git log --no-merges --pretty='- %s (%h)' "${range}" \
    | grep -E "^- ${type}(\([^)]*\))?!?: " || true)"
  if [[ -n "${lines}" ]]; then
    printf '## %s\n\n%s\n\n' "${title}" "${lines}"
  fi
}

printf '# %s\n\n' "${tag}"
section "Features" "feat"
section "Fixes" "fix"
section "Documentation" "docs"
section "Tests" "test"
section "CI" "ci"
section "Chores" "chore"
