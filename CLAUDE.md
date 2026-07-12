# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture Overview

StockAgent is a distributed A-share market analysis platform with microservice nodes communicating via gRPC, backed by MongoDB, Redis, and optionally Milvus.

```
Frontend (Vue3)  →  Web Node (FastAPI)  →  gRPC  →  Data Sync / Inference / Backtest / Listener Nodes
                                                  ↓
                                        MongoDB · Redis · Milvus
```

**Node types** (all share the `AgentServer/` codebase, launched via `NODE_TYPE` env var):
- `web` — FastAPI REST API gateway + JWT auth + WebSocket
- `data_sync` — Tushare market data sync, news collection (10+ sources), daily report generation
- `inference` — LLM analysis workflows (LangChain/LangGraph)
- `backtest_engine` — Quant backtesting engine, 17+ factor models, A-share T+1 rules
- `listener` — Real-time market monitoring and alerts
- `mcp` — Model Context Protocol server (full stack only)

**DataSync** (`DataSync/`) is a standalone service being extracted from `AgentServer/`. It has its own dependencies, config, runtime directories, and Docker setup — it must not import from `AgentServer/`.

## Development Commands

### Frontend (`frontend/`)
```bash
npm install
npm run dev        # Vite dev server → http://localhost:5173
npm run build      # Type-check + production build
npm run lint       # ESLint --fix
npm run format     # Prettier on src/
```

### AgentServer backend (`AgentServer/`)
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Start individual nodes
NODE_TYPE=web python main.py
NODE_TYPE=data_sync python main.py
NODE_TYPE=inference python main.py
NODE_TYPE=backtest_engine python main.py

# Tests / lint / type-check
pytest
ruff check .
mypy .
```

### DataSync standalone (`DataSync/`)
```bash
cp DataSync/.env.example DataSync/.env
# Edit .env: TUSHARE_TOKEN, LLM_API_KEY, MONGO_*, REDIS_*, JWT_SECRET

python DataSync/main.py --check             # env + task registration check
python DataSync/main.py --audit-self-contained  # verify no cross-service imports
python DataSync/main.py --check-startup     # full init then exit (needs live infra)
python DataSync/main.py                     # run the service

# Integrity & recovery
python DataSync/main.py --check-core-integrity --integrity-days 2
python DataSync/main.py --recover-latest-core-gaps
python DataSync/main.py --safe-recover-core-window --integrity-days 4

# Ops monitoring
python DataSync/main.py --ops-summary --integrity-days 3 --job-log-limit 10
python DataSync/main.py --recent-failed-jobs --core-jobs-only
python DataSync/main.py --core-job-runtime-summary --runtime-lookback-hours 24
```

### Docker Compose

```bash
# Lightweight stack (web, data-sync, listener, frontend, mongodb, redis)
cp .env.docker.example .env.docker   # fill JWT_SECRET, MONGO_PASSWORD, TUSHARE_TOKEN, LLM_API_KEY
docker compose --env-file .env.docker up -d --build
docker compose --env-file .env.docker logs -f web
docker compose --env-file .env.docker down

# Full stack (adds inference, backtest, mcp, milvus, minio, etcd)
docker compose -f docker-compose.full.yml --env-file .env.docker up -d --build

# DataSync only (standalone)
cd DataSync && cp .env.docker.example .env.docker
docker compose --env-file .env.docker up --build
```

Frontend Nginx reverse-proxies `/api` and `/ws` to the `web` service.

## Key Configuration

Required env vars (in `AgentServer/.env` or `DataSync/.env`):

| Variable | Purpose |
|---|---|
| `NODE_TYPE` | Which node to start (`web`, `data_sync`, etc.) |
| `TUSHARE_TOKEN` | Tushare Pro API token |
| `LLM_PROVIDER` / `LLM_API_KEY` | LLM service (openai, deepseek, dashscope, zhipu, ollama) |
| `MONGO_*` | MongoDB connection |
| `REDIS_*` | Redis connection |
| `JWT_SECRET` | JWT signing key |

## Code Layout

```
AgentServer/
├── main.py              # unified entry point, reads NODE_TYPE
├── core/
│   ├── settings.py      # Pydantic settings (all env vars)
│   ├── protocols.py     # shared type protocols
│   ├── rpc/             # gRPC client/server wrappers
│   └── managers/        # MongoDB, Redis, DataSource managers
├── src/
│   ├── data_sources/    # Tushare/AkShare/BaoStock/Coze adapters with fallback chain
│   └── collector/       # pluggable news collector framework
└── nodes/
    ├── web/api/         # FastAPI routers
    ├── data_sync/       # collectors (stock/, news/), tasks/, generators/
    ├── inference/       # LangChain/LangGraph workflows
    ├── backtest_engine/ # factor models and backtest engine
    ├── listener/        # real-time monitoring
    └── mcp/             # MCP server

DataSync/                # standalone extraction of data_sync node
├── main.py              # CLI entry with --check / --ops-summary / etc.
├── common/              # shared utilities
├── core/                # settings, managers (mirror of AgentServer/core/)
├── config/              # DataSync-specific config
├── src/                 # data_sources, collector
└── nodes/data_sync/     # the sync node itself

frontend/src/
├── api/                 # Axios API wrappers
├── views/               # page-level Vue components
├── stores/              # Pinia state stores
└── router/index.ts      # route definitions + auth guard (checks localStorage token)
```

## DataSync Isolation Rules

DataSync must remain self-contained:
- Use `python DataSync/main.py --audit-self-contained` to verify no imports from `AgentServer/`, `nodes.web`, `nodes.listener`, or `nodes.inference`
- DataSync reads only `DataSync/.env` or `DataSync/.env.docker`; set `DATASYNC_ALLOW_SHARED_ENV_FALLBACK=0` to disable the shared-env fallback
- Runtime files land in `DataSync/logs/`, `DataSync/data/` (override with `DATASYNC_RUNTIME_DIR`, `DATASYNC_DATA_DIR`)

## Data Source Fallback Chain

Core market data methods use a conservative priority order with per-source timeouts and automatic fallback:
`tushare → baostock → akshare → coze`

Coze is preferred for single-stock, real-time, and enriched requests only.

## CI/CD

`.github/workflows/deploy-feature-monitor.yml` deploys branch `feature-monitor` to Aliyun via SSH using `tools/deploy/deploy_feature_monitor.sh`.
