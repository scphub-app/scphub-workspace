#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

expected=(
  "scphub|https://github.com/scphub-app/scphub.git|main"
  "scphub-backend|https://github.com/scphub-app/scphub-backend.git|main"
  "tools|https://github.com/scphub-app/scphub-tools.git|main"
)

configured_paths="$({ git config -f .gitmodules --get-regexp '^submodule\..*\.path$' || true; } | awk '{print $2}' | sort)"
expected_paths="$(printf '%s\n' "${expected[@]%%|*}" | sort)"

if [[ "$configured_paths" != "$expected_paths" ]]; then
  echo "Unexpected submodule path set" >&2
  printf 'configured:\n%s\nexpected:\n%s\n' "$configured_paths" "$expected_paths" >&2
  exit 1
fi

for item in "${expected[@]}"; do
  IFS='|' read -r path expected_url expected_branch <<<"$item"
  name="$path"
  actual_path="$(git config -f .gitmodules --get "submodule.${name}.path")"
  actual_url="$(git config -f .gitmodules --get "submodule.${name}.url")"
  actual_branch="$(git config -f .gitmodules --get "submodule.${name}.branch")"

  [[ "$actual_path" == "$path" ]] || { echo "$name: unexpected path $actual_path" >&2; exit 1; }
  [[ "$actual_url" == "$expected_url" ]] || { echo "$name: unexpected URL $actual_url" >&2; exit 1; }
  [[ "$actual_branch" == "$expected_branch" ]] || { echo "$name: unexpected branch $actual_branch" >&2; exit 1; }

  read -r mode gitlink _ < <(git ls-files -s -- "$path")
  [[ "$mode" == "160000" ]] || { echo "$path is not a gitlink (mode: $mode)" >&2; exit 1; }
  [[ "$gitlink" =~ ^[0-9a-f]{40}$ ]] || { echo "$path has an invalid gitlink SHA" >&2; exit 1; }
done

echo "Validated .gitmodules and all three gitlinks."
