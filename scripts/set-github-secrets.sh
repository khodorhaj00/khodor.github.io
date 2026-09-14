#!/usr/bin/env bash
# Optional convenience: uploads the four APK signing secrets to the GitHub repository with the
# gh CLI. The same values can be entered by hand under Settings > Secrets and variables > Actions.
#
#   scripts/set-github-secrets.sh [keystore-path]
#
# Requires gh (logged in: `gh auth login`) and keytool. Run it inside the clone so gh resolves the
# repository from the git remote, or set GH_REPO=owner/name.
#
# Environment (all optional):
#   KEYSTORE_PASSWORD  store password; prompted when unset
#   KEY_ALIAS          default "upload"
#   KEY_PASSWORD       default: same as KEYSTORE_PASSWORD (PKCS12 keystores have one password)
set -euo pipefail

die() { echo "set-github-secrets: $*" >&2; exit 1; }

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
keystore="${1:-$repo_root/app/android/app/upload-keystore.jks}"
alias="${KEY_ALIAS:-upload}"

command -v gh > /dev/null || die "gh not found; install it from https://cli.github.com/ or set the secrets in the GitHub UI"
command -v keytool > /dev/null || die "keytool not found; install a JDK (Temurin 17 or 21)"
gh auth status > /dev/null 2>&1 || die "gh is not logged in; run: gh auth login"
[ -f "$keystore" ] || die "$keystore not found; run scripts/gen-keystore.sh first"

if [ -z "${KEYSTORE_PASSWORD:-}" ]; then
  read -rsp "Keystore password: " KEYSTORE_PASSWORD; echo
fi
export KEYSTORE_PASSWORD
KEY_PASSWORD="${KEY_PASSWORD:-$KEYSTORE_PASSWORD}"

# CI writes these into key.properties, which java.util.Properties reads as ISO-8859-1; the
# build-apk workflow rejects anything but printable ASCII, so fail here before uploading.
printable_ascii() { [ "$(printf '%s' "$1" | LC_ALL=C tr -d '\040-\176' | wc -c)" -eq 0 ]; }
printable_ascii "$KEYSTORE_PASSWORD" || die "KEYSTORE_PASSWORD must be printable ASCII (no newline, control or non-ASCII characters)"
printable_ascii "$alias" || die "KEY_ALIAS must be printable ASCII"
printable_ascii "$KEY_PASSWORD" || die "KEY_PASSWORD must be printable ASCII"

# Verify password and alias locally so a typo never ends up as a broken CI secret.
keytool -list -keystore "$keystore" -storepass:env KEYSTORE_PASSWORD -alias "$alias" > /dev/null \
  || die "alias '$alias' or the password is wrong for $keystore"

repo_label="${GH_REPO:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
echo "Setting secrets on $repo_label"

# gh reads the secret value from stdin, so no value is passed as an argument.
base64 < "$keystore" | tr -d '\n' | gh secret set KEYSTORE_BASE64
printf '%s' "$KEYSTORE_PASSWORD" | gh secret set KEYSTORE_PASSWORD
printf '%s' "$alias" | gh secret set KEY_ALIAS
printf '%s' "$KEY_PASSWORD" | gh secret set KEY_PASSWORD

echo
gh secret list
echo
echo "Done. The next 'Build APK' run signs with this key (push to the default branch, run the workflow manually, or push a v* tag)."
