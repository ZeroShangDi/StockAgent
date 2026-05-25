# 提交与暂存规范

## 目的

本文件用于约定当前仓库后续提交、暂存和变更日志维护的统一标准。

除非后续明确修改规则，否则后面的提交都应遵循本文件。

## 提交标准

### 1. 按可审查范围拆分提交

每次提交应尽量控制在单一、清晰、可审查的范围内，例如：

- `文档`
- `数据源`
- `同步链路`
- `监听模块`
- `Web API`
- `前端页面`
- `测试`

如果两类改动可以拆开审查，就不要混在同一个提交里。

### 2. 每次提交前先更新 `docs/CHANGELOG.md`

在每一批代码暂存或提交前，都要先更新：

- [docs/CHANGELOG.md](/Users/shangjunhao/Project/StockAgent/docs/CHANGELOG.md)

要求：

- 只记录有意义的项目变更
- 尽量简洁
- 统一归类到以下小节：
  - `新增`
  - `变更`
  - `修复`
  - `移除`（如适用）

在正式发版前，统一先记录到 `未发布` 小节。

### 3. 按逻辑批次暂存

推荐流程：

1. 明确本次要提交的范围
2. 更新 `docs/CHANGELOG.md`
3. 只暂存属于该范围的文件
4. 检查 staged diff
5. 再提交
6. 手动推送到远程

### 4. 提交信息采用规范前缀加中文说明

从现在开始，本仓库后续提交信息采用：

- `英文 type(scope)` 规范前缀
- 冒号后必须使用中文说明

推荐格式：

- `docs(workflow): 补充变更日志与提交流程规范`
- `feat(data-source): 新增 Coze 工作流适配器`
- `feat(sync): 增加重点股票补库与多源回退`
- `feat(system-status): 增加数据源矩阵并优化加载方式`
- `fix(listener): 修复策略配置与通知 dry-run`
- `test(listener): 补充监听相关验证`
- `chore(config): 补充 .env.example 与配置项`

禁止格式：

- `fix(practice): restore trade markers on chart`
- `feat(strategy-v2): add task run progress`
- `refactor(frontend): simplify task center table`

说明：

- `type` 建议使用常见约定式提交前缀，例如 `feat`、`fix`、`docs`、`test`、`chore`、`refactor`
- `scope` 用于标记改动范围，例如 `data-source`、`sync`、`listener`、`system-status`
- 冒号后面的正文必须使用中文，英文只能出现在专有名词、模块名、技术名或必要缩写中
- 提交前必须自检 `git log -1 --pretty=%s` 的格式，确认正文不是英文短句

### 5. 文档统一使用中文

从现在开始，本仓库新增或维护的项目内文档优先使用中文，包括但不限于：

- `docs` 目录下的规范文档
- `CHANGELOG`
- 提交说明中需要长期保留的文字内容

### 6. 注意保护本地配置和密钥

- 不要暂存真实 token、密码、Webhook 等敏感信息
- 修改 `.env.example` 时不要覆盖本地 `.env` 中已经存在的真实值
- 除非明确要求，不要把本地私有配置纳入提交

## 当前执行规则

本仓库从现在开始默认遵循以下规则：

- 提交按逻辑范围拆分
- 每次提交前先更新 `docs/CHANGELOG.md`
- 提交信息使用 `type(scope): 中文说明` 格式，冒号后的说明必须是中文
- 文档使用中文
- 推送由人工手动执行
