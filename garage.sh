#!/bin/sh
# Run Garage, a free S3-compatible server, on this computer in Docker, so
# data-compare can save reports to a real S3 API without an AWS account.
#
#   ./garage.sh start    first run makes secrets and keys, then starts the server
#   ./garage.sh status   shows the server's health
#   ./garage.sh stop     stops the server (saved reports stay on disk)
#
# Then, in the terminal that runs the API:
#   . ~/.data-compare-garage/env && .venv/bin/uvicorn api:app
#
# Secrets, keys and stored reports live in ~/.data-compare-garage, outside
# the repository, so they can never be committed. The S3 port listens on
# 127.0.0.1 only, so nothing else on the network can reach it.
set -eu

IMAGE="dxflrs/garage:v2.5.0"
NAME="data-compare-garage"
DIR="$HOME/.data-compare-garage"
BUCKET="data-compare-reports"

setup() {
    mkdir -p "$DIR/meta" "$DIR/data"
    chmod 700 "$DIR"
    if [ ! -f "$DIR/garage.toml" ]; then
        # Layout follows Garage's quick start, with data kept on disk, not in /tmp.
        cat > "$DIR/garage.toml" <<EOF
metadata_dir = "/var/lib/garage/meta"
data_dir = "/var/lib/garage/data"
db_engine = "sqlite"
replication_factor = 1

rpc_bind_addr = "[::]:3901"
rpc_public_addr = "127.0.0.1:3901"
rpc_secret = "$(openssl rand -hex 32)"

[s3_api]
s3_region = "garage"
api_bind_addr = "[::]:3900"
root_domain = ".s3.garage.localhost"

[admin]
api_bind_addr = "[::]:3903"
admin_token = "$(openssl rand -base64 32)"
EOF
        chmod 600 "$DIR/garage.toml"
    fi
    if [ ! -f "$DIR/env" ]; then
        cat > "$DIR/env" <<EOF
# Source this file (. ~/.data-compare-garage/env) before starting the API.
export AWS_ENDPOINT_URL_S3="http://localhost:3900"
export AWS_DEFAULT_REGION="garage"
export AWS_ACCESS_KEY_ID="GK$(openssl rand -hex 16)"
export AWS_SECRET_ACCESS_KEY="$(openssl rand -hex 32)"
unset AWS_SESSION_TOKEN AWS_PROFILE
export REPORTS_BUCKET="$BUCKET"
# Garage does not offer S3-managed encryption (SSE-S3), so it is switched off
# here. Leave this unset for real AWS.
export REPORTS_SSE="none"
EOF
        chmod 600 "$DIR/env"
    fi
}

start() {
    setup
    if docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
        echo "Garage is already running."
        return
    fi
    docker rm "$NAME" >/dev/null 2>&1 || true
    # shellcheck disable=SC1091
    . "$DIR/env"
    docker run -d --name "$NAME" \
        -p 127.0.0.1:3900:3900 \
        -v "$DIR/garage.toml:/etc/garage.toml:ro" \
        -v "$DIR/meta:/var/lib/garage/meta" \
        -v "$DIR/data:/var/lib/garage/data" \
        -e GARAGE_DEFAULT_ACCESS_KEY="$AWS_ACCESS_KEY_ID" \
        -e GARAGE_DEFAULT_SECRET_KEY="$AWS_SECRET_ACCESS_KEY" \
        -e GARAGE_DEFAULT_BUCKET="$BUCKET" \
        "$IMAGE" /garage server --single-node --default-bucket >/dev/null
    echo "Garage started on http://localhost:3900 with bucket $BUCKET."
    echo "Next: . $DIR/env && .venv/bin/uvicorn api:app"
}

case "${1:-}" in
    start) start ;;
    stop) docker stop "$NAME" >/dev/null && echo "Garage stopped. Reports stay in $DIR/data." ;;
    status) docker exec "$NAME" /garage status ;;
    *) echo "usage: $0 start|status|stop" >&2; exit 2 ;;
esac
