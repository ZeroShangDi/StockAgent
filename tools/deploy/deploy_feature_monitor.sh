#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="${DEPLOY_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-feature-monitor}"
DEPLOY_ENV_FILE="${DEPLOY_ENV_FILE:-.env.docker}"
DEPLOY_COMPOSE_FILES="${DEPLOY_COMPOSE_FILES:-docker-compose.lite.yml}"

if ! command -v git >/dev/null 2>&1; then
  echo "[deploy] git is required"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[deploy] docker is required"
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "[deploy] docker compose or docker-compose is required"
  exit 1
fi

COMPOSE_FILE_ARGS=()
OLD_IFS="$IFS"
IFS=',: '
read -r -a _compose_files <<< "$DEPLOY_COMPOSE_FILES"
IFS="$OLD_IFS"

for compose_file in "${_compose_files[@]}"; do
  [ -n "$compose_file" ] || continue
  if [ ! -f "$compose_file" ]; then
    echo "[deploy] missing compose file: $compose_file"
    exit 1
  fi
  COMPOSE_FILE_ARGS+=(-f "$compose_file")
done

cd "$PROJECT_ROOT"

echo "[deploy] project root: $PROJECT_ROOT"
echo "[deploy] branch: $DEPLOY_BRANCH"
echo "[deploy] compose files: $DEPLOY_COMPOSE_FILES"

if [ ! -f "$DEPLOY_ENV_FILE" ]; then
  echo "[deploy] missing env file: $DEPLOY_ENV_FILE"
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "[deploy] worktree is dirty, refusing to deploy"
  exit 1
fi

git fetch origin "$DEPLOY_BRANCH"

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" != "$DEPLOY_BRANCH" ]; then
  if git show-ref --verify --quiet "refs/heads/$DEPLOY_BRANCH"; then
    git checkout "$DEPLOY_BRANCH"
  else
    git checkout -b "$DEPLOY_BRANCH" --track "origin/$DEPLOY_BRANCH"
  fi
fi

git pull --ff-only origin "$DEPLOY_BRANCH"

"${COMPOSE_CMD[@]}" "${COMPOSE_FILE_ARGS[@]}" --env-file "$DEPLOY_ENV_FILE" up -d --build
"${COMPOSE_CMD[@]}" "${COMPOSE_FILE_ARGS[@]}" --env-file "$DEPLOY_ENV_FILE" ps

echo "[deploy] done"
