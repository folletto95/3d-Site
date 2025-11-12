#!/usr/bin/env bash
set -euo pipefail

# Determine repository root from script location.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

VERIFY=1
BUILD_ARGS=()

while (($#)); do
    case "$1" in
        --skip-verify)
            VERIFY=0
            ;;
        --verify)
            VERIFY=1
            ;;
        *)
            BUILD_ARGS+=("$1")
            ;;
    esac
    shift
done

cd "$REPO_ROOT"

echo "[build-slicer-api] Using repository root as build context: $REPO_ROOT"

IID_FILE="$(mktemp)"

cleanup() {
    rm -f "$IID_FILE"
}
trap cleanup EXIT

docker build -f services/slicer-api/Dockerfile --iidfile "$IID_FILE" "${BUILD_ARGS[@]}" .

if [[ "$VERIFY" -eq 1 ]]; then
    IMAGE_ID="$(cat "$IID_FILE")"
    echo "[build-slicer-api] Verifying PrusaSlicer binary inside image ($IMAGE_ID)"
    docker run --rm --entrypoint PrusaSlicer "$IMAGE_ID" --version >/dev/null
    echo "[build-slicer-api] PrusaSlicer detected."
fi
