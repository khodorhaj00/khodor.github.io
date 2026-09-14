#!/usr/bin/env bash
# Generates the Android upload keystore that signs release APKs and prints the values for the
# four GitHub Actions secrets (KEYSTORE_BASE64, KEYSTORE_PASSWORD, KEY_ALIAS, KEY_PASSWORD).
#
#   scripts/gen-keystore.sh [keystore-path]
#
# Default path: app/android/app/upload-keystore.jks (git-ignored). When the keystore is created
# there, app/android/key.properties is written as well so a local `flutter build apk --release`
# is signed with the same key as CI.
#
# Environment (all optional):
#   KEYSTORE_PASSWORD  store password, at least 6 characters; prompted when unset
#   KEY_ALIAS          key alias, default "upload"
#   DNAME              certificate subject, default "CN=Rhino Viewer, O=Styro3D"
#   VALIDITY_DAYS      certificate validity, default 10000 (Google Play requires 25+ years)
#
# keytool creates PKCS12 keystores, which have a single password for the store and the key, so
# KEY_PASSWORD is always the same value as KEYSTORE_PASSWORD.
set -euo pipefail

die() { echo "gen-keystore: $*" >&2; exit 1; }

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
keystore="${1:-$repo_root/app/android/app/upload-keystore.jks}"
alias="${KEY_ALIAS:-upload}"
dname="${DNAME:-CN=Rhino Viewer, O=Styro3D}"
validity="${VALIDITY_DAYS:-10000}"

command -v keytool > /dev/null || die "keytool not found; install a JDK (Temurin 17 or 21) or use <Android Studio>/jbr/bin/keytool"
[ -e "$keystore" ] && die "$keystore already exists; refusing to overwrite (a replaced upload key forces every user to uninstall before updating)"

if [ -z "${KEYSTORE_PASSWORD:-}" ]; then
  read -rsp "Keystore password (min 6 characters): " KEYSTORE_PASSWORD; echo
  read -rsp "Repeat password: " repeat; echo
  [ "$KEYSTORE_PASSWORD" = "$repeat" ] || die "passwords do not match"
fi
[ "${#KEYSTORE_PASSWORD}" -ge 6 ] || die "password must be at least 6 characters (keytool minimum)"
export KEYSTORE_PASSWORD

mkdir -p "$(dirname "$keystore")"
# Passwords are passed through the environment so they never appear in the process list.
keytool -genkeypair -keystore "$keystore" -keyalg RSA -keysize 2048 -validity "$validity" \
  -alias "$alias" -storepass:env KEYSTORE_PASSWORD -keypass:env KEYSTORE_PASSWORD -dname "$dname"
chmod 600 "$keystore"

echo
echo "Created $keystore"
keytool -list -keystore "$keystore" -storepass:env KEYSTORE_PASSWORD -alias "$alias" | grep -E 'fingerprint'

android_dir="$repo_root/app/android"
if [ "$(cd "$(dirname "$keystore")" && pwd)" = "$android_dir/app" ]; then
  printf 'storeFile=%s\nstorePassword=%s\nkeyAlias=%s\nkeyPassword=%s\n' \
    "$(basename "$keystore")" "$KEYSTORE_PASSWORD" "$alias" "$KEYSTORE_PASSWORD" > "$android_dir/key.properties"
  chmod 600 "$android_dir/key.properties"
  echo "Wrote $android_dir/key.properties (git-ignored): local release builds are now signed."
fi

b64="$(base64 < "$keystore" | tr -d '\n')"
cat <<REPORT

Back the .jks up somewhere safe: it cannot be regenerated, and an APK signed with a different key
cannot update an installed one.

GitHub Actions secrets (repository Settings > Secrets and variables > Actions), or run
scripts/set-github-secrets.sh "$keystore" to upload them with the gh CLI:

  KEYSTORE_BASE64    $b64
  KEYSTORE_PASSWORD  (the password you entered)
  KEY_ALIAS          $alias
  KEY_PASSWORD       (same value as KEYSTORE_PASSWORD)
REPORT
