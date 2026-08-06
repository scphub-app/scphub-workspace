#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

denied_path_pattern='(^|/)(App备案信息|backups|data)(/|$)|^document-packs/.*/source/|^document-packs/.*\.(html|zip)$|^document-packs/.*/(source|selection)\.json$|^document-packs/.*(audit|discovery|candidates).*\.json$|(^|/)(\.codex|\.claude)(/|$)|(^|/)(\.env($|\.)|\.dev\.vars($|\.)|\.netrc$|GoogleService-Info\.plist$|google-services\.json$)|\.(pem|key|p8|p12|pfx|mobileprovision|provisionprofile|keystore|jks|kdbx)$'

denied=0
while IFS= read -r tracked; do
  if [[ "$tracked" =~ $denied_path_pattern ]] && [[ ! "$tracked" =~ \.example$ ]]; then
    echo "Denied tracked path: $tracked" >&2
    denied=1
  fi
done < <(git ls-files)
(( denied == 0 )) || exit 1

max_bytes=$((10 * 1024 * 1024))
oversized=0
while read -r mode object _ path; do
  [[ "$mode" == "160000" ]] && continue
  size="$(git cat-file -s "$object")"
  if (( size > max_bytes )); then
    echo "Tracked file exceeds 10 MiB: $path ($size bytes)" >&2
    oversized=1
  fi
done < <(git ls-files -s)
(( oversized == 0 )) || exit 1

credential_pattern='AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|github_pat_[A-Za-z0-9_]{40,}|gh[pousr]_[A-Za-z0-9_]{36,}|-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'
if git grep -I -n -E "$credential_pattern" -- ':!*.example' ':!*.md'; then
  echo "High-confidence credential signature found in tracked content." >&2
  exit 1
fi

echo "Root repository hygiene checks passed."
