# DataSync 工作区边界说明

本文档对应 `DS-P0-01：冻结独立 DataSync 工作区边界`，用于说明当前 `DataSync/` 独立重构目录中哪些文件属于有效重构资产，哪些属于运行产物或本地私有配置，避免后续 heartbeat 误提交、误删或重复实现。

当前日期：`2026-05-29`

## 1. 当前 Git 状态摘要

当前仓库中 `DataSync/` 已被 Git 跟踪的文件只有 5 个：

- `DataSync/Dockerfile`
- `DataSync/README.md`
- `DataSync/docker-compose.yml`
- `DataSync/main.py`
- `DataSync/requirements.txt`

这些文件当前已有未提交修改，属于独立 `DataSync` 重构线的一部分，后续可以继续整理，但按照当前约定不要分散小提交，最终统一提交。

当前 `DataSync/` 还有大量未跟踪文件和目录，主要是从 `AgentServer` 拆出的独立服务骨架、配置、采集器、任务、数据源适配器和管理器代码。它们大多属于有效重构资产，但需要先通过独立性检查、配置检查和最小启动检查后再纳入统一提交。

## 2. 可以纳入重构的有效资产

下面这些目录/文件属于 `DataSync` 独立服务重构资产，后续任务可以修改、整理、测试，并在统一提交点纳入版本控制。

### 2.1 服务入口与部署文件

- `DataSync/Dockerfile`
- `DataSync/docker-compose.yml`
- `DataSync/main.py`
- `DataSync/requirements.txt`
- `DataSync/.dockerignore`
- `DataSync/.gitignore`
- `DataSync/.env.example`
- `DataSync/.env.docker.example`

注意：

- `.env.example` 和 `.env.docker.example` 可以提交。
- `.env` 和 `.env.docker` 不能提交。
- Docker 与环境变量默认值必须以 4C8G 保守运行为约束。

### 2.2 独立运行依赖代码

- `DataSync/common/`
- `DataSync/core/`
- `DataSync/src/`
- `DataSync/nodes/`

这些目录目前承担独立 DataSync 所需的公共模型、管理器、RPC、配置、数据源适配、采集器、任务和服务逻辑。后续改动时需要持续保证：

- 不通过 `PYTHONPATH` 反向依赖 `AgentServer`。
- 不重新引入 `nodes.web`、`nodes.listener`、`nodes.inference` 等跨服务依赖。
- 本地同名包必须解析到 `DataSync/` 内部。

### 2.3 配置与提示词资产

- `DataSync/config/`
- `DataSync/core/prompts/`

这些文件可以纳入重构资产，但需要区分：

- 可提交：默认配置、提示词模板、示例配置。
- 不可提交：包含 token、账号、私钥、真实生产连接串的本地配置。

### 2.4 部署辅助文件

- `DataSync/deploy/`

当前主要包含 Mongo 初始化脚本。可以作为独立部署资产保留，但后续需要确认它不会和仓库根部署脚本冲突。

## 3. 不应提交的本地私有配置与运行产物

下面这些内容不得纳入提交。

### 3.1 本地私有配置

- `DataSync/.env`
- `DataSync/.env.docker`

原因：

- 可能包含数据库地址、token、账号密码、服务密钥。
- 服务器、本地、测试环境配置不应混在源码中。

处理方式：

- 保留本地文件。
- 只维护 `.env.example` 和 `.env.docker.example`。
- 如果后续要说明生产配置，写入文档，不写真实秘钥。

### 3.2 Python 编译缓存

- `DataSync/**/__pycache__/`
- `DataSync/**/*.pyc`

原因：

- 运行时生成，无源码价值。
- 会污染提交并影响代码审查。

处理方式：

- 应被 `DataSync/.gitignore` 或仓库根 `.gitignore` 忽略。
- 不需要删除，除非后续专门清理工作区。

### 3.3 日志与运行数据

- `DataSync/logs/`
- `DataSync/data/`

原因：

- 属于运行产物。
- 可能快速增长。
- 可能包含本地路径、接口响应、错误信息或临时数据库文件。

处理方式：

- 不提交。
- Docker 或本地运行时按目录挂载/生成。

## 4. 当前需要谨慎处理的外部未提交项

当前工作区还有这些与本轮 DataSync 边界任务无关或暂不确认归属的改动：

- `frontend/src/components.d.ts`
- `CLAUDE.md`
- `docs/datasync-task-timeline.md`

处理原则：

- `frontend/src/components.d.ts` 属于前端生成文件，DataSync 重构任务不要触碰。
- `CLAUDE.md` 归属不明，不能擅自修改或提交。
- `docs/datasync-task-timeline.md` 是 DataSync 任务时间轴文档，内容有参考价值，但当前仍未跟踪；是否纳入统一提交需要后续确认。

## 5. 后续任务的文件操作规则

### 5.1 修改规则

- DataSync 重构任务可以修改 `DataSync/` 内有效资产和 `docs/DATASYNC_*.md`。
- 如果需要修改仓库根 Docker Compose 或 `AgentServer` 文件，必须说明原因，且只为兼容部署、旧链路对照或迁移边界服务。
- 不要为了通过检查而删除用户未确认的未提交文件。

### 5.2 提交规则

- 后续 DataSync 代码重构统一提交，不按 heartbeat 每轮小提交。
- 每轮 heartbeat 可以修改文件并运行验证，但不要 commit。
- 到统一提交点时，只 stage 与 DataSync 重构有关的文件。
- 提交信息必须符合中文规范，冒号后必须是中文。

### 5.3 验证规则

每轮至少做最小验证：

- 文档改动：`git diff --check`。
- Python 改动：优先做编译检查或相关单元测试。
- 配置改动：执行配置加载检查。
- Docker 改动：执行 `docker compose config` 或等价检查。

如果验证因环境限制无法执行，必须在 heartbeat 报告中说明。

## 6. DS-P0-01 验收状态

当前状态：`已完成文档边界冻结，等待后续任务继续验证代码资产`

已完成：

- 明确了已跟踪文件和未跟踪重构资产的边界。
- 明确了 `.env`、日志、`data/`、`__pycache__` 等不得提交。
- 明确了 `frontend/src/components.d.ts`、`CLAUDE.md` 等无关文件不可误碰。
- 明确了后续 heartbeat 修改、验证、统一提交规则。

剩余风险：

- `DataSync/` 未跟踪代码量较大，后续仍需要通过 `--audit-self-contained`、`--check`、`--check-startup` 等命令逐步确认可用性。
- 当前文档只冻结边界，不代表独立 DataSync 已经完成生产可用验证。
