# DataSync

独立的 `DataSync` 服务目录，当前阶段先复用 `AgentServer` 内的基础设施和 `DataSyncNode` 实现，通过单独入口验证它已经可以作为独立服务启动。

这一步的目标是：

- `DataSync/` 可以单独运行
- `AgentServer/` 里的旧实现先保留不动
- 后续确认稳定后，再继续把内部模块逐步迁移出来

## 本地校验

使用项目已有虚拟环境：

```bash
AgentServer/venv/bin/python DataSync/main.py --check
```

这会完成：

- 环境文件加载
- 独立运行目录初始化
- 任务注册检查

如果要做一次更接近真实启动链路的验证：

```bash
AgentServer/venv/bin/python DataSync/main.py --check-startup
```

它会初始化 `Redis`、`MongoDB`、数据源管理器、`LLM`、调度器和 RPC 服务，然后立刻退出。

如果需要直接启动：

```bash
AgentServer/venv/bin/python DataSync/main.py
```

也支持从 `DataSync/` 目录内部启动：

```bash
cd DataSync
../AgentServer/venv/bin/python main.py
```

## 容器方式

```bash
cd DataSync
docker compose up --build
```

容器会：

- 使用 `DataSync/Dockerfile`
- 读取仓库根目录的 `.env.docker`
- 启动独立的 `data-sync + mongo + redis`
- 将日志和数据固定落在 `DataSync` 自己的运行目录

## 当前实现边界

当前版本仍然通过 `PYTHONPATH` 引入 `../AgentServer` 中的共享模块，例如：

- `core/`
- `common/`
- `src/`
- `nodes/data_sync/`

这意味着它已经能独立启动，但还不是最终形态的完全物理拆分。后续确认可运行后，再继续做真正的模块迁移与依赖收敛。

## 运行目录约定

默认情况下，独立 `DataSync` 会把运行时文件固定到自身目录下：

- 日志：`DataSync/logs/`
- 本地数据：`DataSync/data/`
- Milvus Lite：`DataSync/data/milvus_lite.db`

如果需要自定义，可以通过下面的环境变量覆盖：

- `DATASYNC_RUNTIME_DIR`
- `DATASYNC_DATA_DIR`
- `OBS_LOG_DIR`
- `MILVUS_URI`
