#!/usr/bin/env bash
# Builds .env from AWS Systems Manager Parameter Store, so secrets never live in git or in your shell history.
# Every parameter under the prefix becomes one variable: /wallet-platform/prod/JWT_SECRET -> JWT_SECRET=...
# Needs an instance role that may call ssm:GetParametersByPath on that prefix (see docs/DEPLOYMENT.md).
#
#   bash deploy/render_env_from_ssm.sh            # writes ./.env (mode 600)
#   SSM_PREFIX=/wallet-platform/staging bash deploy/render_env_from_ssm.sh /tmp/staging.env
set -euo pipefail

PREFIX="${SSM_PREFIX:-/wallet-platform/prod}"
OUT="${1:-.env}"

umask 077
aws ssm get-parameters-by-path --path "$PREFIX" --recursive --with-decryption \
  --query 'Parameters[].[Name,Value]' --output text \
  | while IFS=$'\t' read -r name value; do
      printf '%s=%s\n' "${name##*/}" "$value"
    done > "$OUT"
chmod 600 "$OUT"

count="$(wc -l < "$OUT")"
[ "$count" -gt 0 ] || { echo "No parameters found under $PREFIX" >&2; rm -f "$OUT"; exit 1; }
echo "Wrote $OUT with $count variables (names only: $(cut -d= -f1 "$OUT" | tr '\n' ' '))"
