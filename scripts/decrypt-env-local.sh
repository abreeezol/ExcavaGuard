#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT_FILE="${ROOT_DIR}/.env.local.enc"
OUTPUT_FILE="${ROOT_DIR}/.env.local"

FORCE=0
if [[ "${1:-}" == "--force" ]]; then
  FORCE=1
fi

if [[ ! -f "${INPUT_FILE}" ]]; then
  echo "Missing encrypted file: ${INPUT_FILE}" >&2
  exit 1
fi

if [[ -f "${OUTPUT_FILE}" && "${FORCE}" != "1" ]]; then
  echo "${OUTPUT_FILE} already exists. Re-run with --force to overwrite." >&2
  exit 1
fi

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required to decrypt .env.local.enc." >&2
  exit 1
fi

if [[ -z "${EXCAVAGUARD_ENV_PASSPHRASE:-}" ]]; then
  read -r -s -p "Passphrase for .env.local.enc: " EXCAVAGUARD_ENV_PASSPHRASE
  echo
fi
export EXCAVAGUARD_ENV_PASSPHRASE

TMP_FILE="$(mktemp "${OUTPUT_FILE}.tmp.XXXXXX")"
cleanup() {
  rm -f "${TMP_FILE}"
}
trap cleanup EXIT

openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -in "${INPUT_FILE}" \
  -out "${TMP_FILE}" \
  -pass env:EXCAVAGUARD_ENV_PASSPHRASE

chmod 600 "${TMP_FILE}"
mv "${TMP_FILE}" "${OUTPUT_FILE}"
trap - EXIT

echo "Decrypted ${OUTPUT_FILE}"
