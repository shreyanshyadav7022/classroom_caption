#!/bin/zsh
# Trust Lekha's local HTTPS cert in your Mac login keychain (Chrome reads this).
set -e
cd "$(dirname "$0")"
CERT="$PWD/certs/cert.pem"
if [[ ! -f "$CERT" ]]; then
  echo "Missing $CERT"
  exit 1
fi
echo "You will be asked for your Mac password."
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "$CERT"
echo
echo "Done. Fully quit Chrome (Cmd+Q) and reopen:"
echo "  https://localhost:8005/teacher"
echo "Do NOT use http:// or 0.0.0.0"
