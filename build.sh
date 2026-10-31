#!/usr/bin/env bash
# One service: build the console in ui/, then install the API beside it.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

if ! command -v npm >/dev/null 2>&1; then
  NODE_VERSION="v22.14.0"
  curl -fsSL "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-linux-x64.tar.gz" -o /tmp/node.tar.gz
  mkdir -p /tmp/node
  tar -xzf /tmp/node.tar.gz -C /tmp/node --strip-components=1
  export PATH="/tmp/node/bin:${PATH}"
fi

cd "${ROOT}/ui"
npm ci
npm run build

cd "${ROOT}"
pip install -r requirements.txt
