# DataSync 统一提交范围审查

更新时间：2026-06-03

本文用于统一提交前确认哪些改动应纳入 DataSync 重构，哪些需要排除或单独确认，避免最终提交混入 unrelated 文件。

## 建议纳入统一提交

### 独立 DataSync 主体

- `DataSync/.dockerignore`
- `DataSync/.env.docker.example`
- `DataSync/.env.example`
- `DataSync/.gitignore`
- `DataSync/Dockerfile`
- `DataSync/README.md`
- `DataSync/docker-compose.yml`
- `DataSync/main.py`
- `DataSync/requirements.txt`
- `DataSync/common/`
- `DataSync/config/`
- `DataSync/core/`
- `DataSync/deploy/`
- `DataSync/nodes/`
- `DataSync/src/`
- `DataSync/tests/`

理由：这些文件构成独立 DataSync 的代码、配置、运行入口、Docker 部署、能力目录、采集器、运维命令和测试套件。

### AgentServer 配套改动

- `AgentServer/core/managers/mongo_manager.py`
- `AgentServer/core/settings.py`
- `AgentServer/nodes/web/api/market.py`
- `AgentServer/nodes/web/api/system.py`
- `AgentServer/nodes/web/api/system_sync.py`
- `AgentServer/tests/web/test_system_sync_readiness.py`

理由：这些是 Web/系统页读取 DataSync ready marker、能力目录、补缺队列、运维事件，以及 Mongo/配置保守默认的配套接口和测试。

### 前端系统状态页配套改动

- `frontend/src/api/modules/system.ts`
- `frontend/src/api/types.ts`
- `frontend/src/views/system/SystemStatusView.vue`

理由：这些是系统能力状态页展示 DataSync 状态、可恢复性、补缺入队、队列操作和运维事件的前端闭环。

### Docker 与环境变量

- `.env.docker.example`
- `docker-compose.yml`
- `docker-compose.full.yml`

理由：这些文件承载 4C8G 保守默认、资源限制、Mongo/Redis 安全绑定、DataSync 并发与补缺预算等部署层保护。

### 文档

- `docs/CHANGELOG.md`
- `docs/DATASYNC_ARCHITECTURE_AND_CAPABILITIES.md`
- `docs/DATASYNC_MIGRATION_PLAN.md`
- `docs/DATASYNC_OPERATIONS.md`
- `docs/DATASYNC_REFACTOR_TASK_BREAKDOWN.md`
- `docs/DATASYNC_WORKSPACE_BOUNDARY.md`
- `docs/datasync-task-timeline.md`
- `docs/DATASYNC_UNIFIED_COMMIT_SCOPE_REVIEW.md`

理由：这些文档覆盖架构、能力、任务拆解、迁移边界、运维手册、执行时间线和最终提交范围。

## 建议排除或单独确认

### `frontend/src/components.d.ts`

建议：默认排除，除非最终前端构建必须依赖它并确认这些 Element Plus 声明来自本次 DataSync 状态页。

原因：当前 diff 新增 `ElCol`、`ElDropdown`、`ElDropdownItem`、`ElDropdownMenu`、`ElRow`、`ElStep`、`ElSteps` 等自动生成声明，更像之前策略中心/任务弹窗 UI 调整的遗留生成物，不是本轮 DataSync 重构的核心交付。

### `CLAUDE.md`

建议：默认排除，或作为独立提交处理。

原因：这是 Claude Code 工作指南，与 DataSync 重构代码和运维闭环无直接依赖。

## 不应提交的运行生成物

以下文件当前存在于工作区，但未出现在 `git status --short` 的待提交列表里，应继续保持忽略：

- `DataSync/.env`
- `DataSync/.env.docker`
- `DataSync/logs/data_sync.log`
- `DataSync/**/__pycache__/`
- `DataSync/**/*.pyc`

## 统一提交前建议验证

在真正统一提交前，建议至少执行：

```bash
PYTHONWARNINGS=error::DeprecationWarning PYTHONPATH=DataSync AgentServer/venv/bin/python -m unittest discover -s DataSync/tests -v
PYTHONPATH=AgentServer AgentServer/venv/bin/python -m unittest AgentServer.tests.web.test_system_sync_readiness -v
AgentServer/venv/bin/python DataSync/main.py --check
AgentServer/venv/bin/python DataSync/main.py --audit-self-contained
npm run build --prefix frontend
git diff --check
```

如果要按推荐范围 staging，应先显式排除 `frontend/src/components.d.ts` 和 `CLAUDE.md`，确认后再决定是否单独处理。

## 2026-06-03 验证记录

本轮已执行统一提交前核心验证矩阵：

```bash
PYTHONWARNINGS=error::DeprecationWarning PYTHONPATH=DataSync AgentServer/venv/bin/python -m unittest discover -s DataSync/tests -v
PYTHONPATH=AgentServer AgentServer/venv/bin/python -m unittest AgentServer.tests.web.test_system_sync_readiness -v
PYTHONPATH=DataSync AgentServer/venv/bin/python DataSync/main.py --check
PYTHONPATH=DataSync AgentServer/venv/bin/python DataSync/main.py --audit-self-contained
npm run build --prefix frontend
```

验证结果：

- DataSync 全量单元测试通过：`102` 个测试。
- AgentServer 系统同步接口测试通过：`12` 个测试。
- `DataSync/main.py --check` 通过，保守档只注册 `12` 个核心任务。
- `DataSync/main.py --audit-self-contained` 通过，审计 `127` 个 DataSync 模块，未发现禁止依赖。
- 前端生产构建通过；构建过程只出现大 chunk 体积提示，不影响本次 DataSync 功能闭环。

注意：本轮验证会读取本地 `DataSync/.env`，该文件为运行配置文件，仍不应纳入提交。

## 2026-06-03 Staging 预演清单

本轮只做预演，不实际执行 `git add`。最终统一提交时建议使用显式路径 staging，避免 `git add .` 带入 `frontend/src/components.d.ts`、`CLAUDE.md` 或运行生成物。

建议 staging 命令：

```bash
git add \
  .env.docker.example \
  docker-compose.yml \
  docker-compose.full.yml \
  AgentServer/core/managers/mongo_manager.py \
  AgentServer/core/settings.py \
  AgentServer/nodes/web/api/market.py \
  AgentServer/nodes/web/api/system.py \
  AgentServer/nodes/web/api/system_sync.py \
  AgentServer/tests/web/test_system_sync_readiness.py \
  DataSync/.dockerignore \
  DataSync/.env.docker.example \
  DataSync/.env.example \
  DataSync/.gitignore \
  DataSync/Dockerfile \
  DataSync/README.md \
  DataSync/docker-compose.yml \
  DataSync/main.py \
  DataSync/requirements.txt \
  DataSync/common \
  DataSync/config \
  DataSync/core \
  DataSync/deploy \
  DataSync/nodes \
  DataSync/src \
  DataSync/tests \
  docs/CHANGELOG.md \
  docs/DATASYNC_ARCHITECTURE_AND_CAPABILITIES.md \
  docs/DATASYNC_MIGRATION_PLAN.md \
  docs/DATASYNC_OPERATIONS.md \
  docs/DATASYNC_REFACTOR_TASK_BREAKDOWN.md \
  docs/DATASYNC_UNIFIED_COMMIT_SCOPE_REVIEW.md \
  docs/DATASYNC_WORKSPACE_BOUNDARY.md \
  docs/datasync-task-timeline.md \
  frontend/src/api/modules/system.ts \
  frontend/src/api/types.ts \
  frontend/src/views/system/SystemStatusView.vue
```

建议 staging 后复核：

```bash
git diff --cached --name-only
git diff --cached --check
```

复核时必须确认暂存区不包含：

- `frontend/src/components.d.ts`
- `CLAUDE.md`
- `DataSync/.env`
- `DataSync/.env.docker`
- `DataSync/logs/`
- `__pycache__`
- `*.pyc`
