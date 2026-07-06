#!/bin/bash

IMAGE=${1:-quay.io/karmab/ai-grid-demo:latest}

podman machine start 2>/dev/null
podman rmi -f "$IMAGE" 2>/dev/null
podman manifest rm "$IMAGE" 2>/dev/null
podman manifest create "$IMAGE"
podman build --platform linux/amd64,linux/arm64 --manifest "$IMAGE" -f Dockerfile .
podman manifest push --all "$IMAGE" "docker://$IMAGE"
