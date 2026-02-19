#!/bin/bash
# Unmount the DuckDB SSHFS mount
# Run after: docker compose down (if you want to free the connection)

set -e

MOUNT_POINT="$(cd "$(dirname "$0")/.." && pwd)/data/mimic-cxr"

if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    fusermount -u "$MOUNT_POINT"
    echo "✓ Unmounted $MOUNT_POINT"
else
    echo "Not mounted: $MOUNT_POINT"
fi
