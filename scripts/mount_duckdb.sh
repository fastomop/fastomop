#!/bin/bash
# Mount DuckDB from omop-mimic node via SSHFS
# Run this before: docker compose up
#
# Prerequisites:
#   sudo apt install sshfs
#   SSH key auth to ubuntu@omop-mimic (or ubuntu@10.211.116.159)
#
# Security group: Port 22 (SSH) must be open from this node to omop-mimic
# If 'omop-mimic' doesn't resolve, use: OMOP_MIMIC_HOST=10.211.116.159 ./scripts/mount_duckdb.sh

set -e

REMOTE_HOST="${OMOP_MIMIC_HOST:-omop-mimic}"
REMOTE_USER="${OMOP_MIMIC_USER:-ubuntu}"
REMOTE_PATH="mimic-cxr"
MOUNT_POINT="$(cd "$(dirname "$0")/.." && pwd)/data/mimic-cxr"

if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    echo "Already mounted: $MOUNT_POINT"
    ls -la "$MOUNT_POINT"
    exit 0
fi

mkdir -p "$MOUNT_POINT"
echo "Mounting $REMOTE_USER@$REMOTE_HOST:~/$REMOTE_PATH -> $MOUNT_POINT"
# Use uid/gid so Docker container (fastomop user) can read; or add -o allow_other if user_allow_other in /etc/fuse.conf
sshfs "$REMOTE_USER@$REMOTE_HOST:~/$REMOTE_PATH" "$MOUNT_POINT" -o default_permissions

if [ -f "$MOUNT_POINT/mimic_to_omop.duckdb" ]; then
    echo "✓ DuckDB file found: $MOUNT_POINT/mimic_to_omop.duckdb"
else
    echo "⚠ Warning: mimic_to_omop.duckdb not found at mount point"
    ls -la "$MOUNT_POINT"
fi
