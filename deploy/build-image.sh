#!/bin/sh
# Run on the Mac, from the repository root: sh deploy/build-image.sh trial
set -eu
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
tag="${1:-trial}"
case "$tag" in
  ""|*[!a-zA-Z0-9_.-]*) echo "Invalid image tag" >&2; exit 1 ;;
esac
docker version >/dev/null
if command -v docker-buildx >/dev/null 2>&1; then
  docker-buildx build --platform linux/amd64 --load --tag "excavaguard:$tag" .
else
  docker buildx build --platform linux/amd64 --load --tag "excavaguard:$tag" .
fi
mkdir -p .artifacts/deploy
docker save --output ".artifacts/deploy/excavaguard-$tag.tar" "excavaguard:$tag"
echo "Image archive: .artifacts/deploy/excavaguard-$tag.tar"
echo "Upload this archive only; credentials are configured separately on the server."
