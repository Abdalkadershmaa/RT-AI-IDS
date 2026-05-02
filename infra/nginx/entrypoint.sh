#!/bin/sh
set -eu

mkdir -p /etc/nginx/certs
if [ ! -f /etc/nginx/certs/tls.crt ] || [ ! -f /etc/nginx/certs/tls.key ]; then
  openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
    -keyout /etc/nginx/certs/tls.key \
    -out /etc/nginx/certs/tls.crt \
    -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
fi

exec "$@"
