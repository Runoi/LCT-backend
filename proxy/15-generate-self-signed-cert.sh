#!/bin/sh
# Generates a self-signed certificate on first start so HTTPS works without manual steps.
# The certificate lives in a named volume and is reused on later starts.
set -eu

CERT_DIR=/etc/nginx/certs
CERT="$CERT_DIR/server.crt"
KEY="$CERT_DIR/server.key"

if [ -s "$CERT" ] && [ -s "$KEY" ]; then
    echo "tls: reusing existing certificate in $CERT_DIR"
    exit 0
fi

mkdir -p "$CERT_DIR"
openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
    -keyout "$KEY" -out "$CERT" \
    -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
chmod 600 "$KEY"
echo "tls: generated self-signed certificate in $CERT_DIR"
