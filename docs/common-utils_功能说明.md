# 公共工具与模型模块 功能说明

## 概述

公共工具与模型模块位于 `DataSync/common/` 目录下，为 DataSync 所有其他模块提供复用的工具函数、数据模型、枚举定义和日志基础设施。

```
DataSync/common/
├── utils/
│   ├── market_time.py      # A股市场时间工具
│   ├── converters.py       # 数据类型转换
│   └── crypto.py           # 加密工具
├── models/
│   └── stock.py            # 股票相关数据模型
├── enums/
│   ├── node.py             # 节点/任务枚举
│   ├── market.py           # 市场周期枚举
│   ├── trade.py            # 交易/策略枚举
│   └── backtest.py         # 回测枚举
└── logger/
    ├── loki_logger.py      # Loki 日志集成
    └── structured.py       # 结构化日志工具
```

---

## 1. 市场时间工具 (common/utils/market_time.py)

### 1.1 核心设计

统一使用 `Asia/Shanghai` 时区（`ZoneInfo("Asia/Shanghai")`），避免部署在 UTC 服务器时盘中逻辑误判。

### 1.2 函数详解

#### market_now(value: datetime | None = None) -> datetime

返回上海时区当前时间，或把给定时间转换到上海时区。

- 无参数时：返回 `datetime.now(MARKET_TIMEZONE)`
- 传入无时区 datetime：附加 `MARKET_TIMEZONE`
- 传入有时区 datetime：通过 `astimezone()` 转换

```python
from common.utils.market_time import market_now

# 获取上海当前时间
now = market_now()
# datetime(2026, 6, 21, 14, 30, 0, tzinfo=ZoneInfo('Asia/Shanghai'))

# 转换 UTC 时间到上海时区
from datetime import datetime, timezone
utc_time = datetime(2026, 6, 21, 6, 30, tzinfo=timezone.utc)
cn_time = market_now(utc_time)
# datetime(2026, 6, 21, 14, 30, tzinfo=ZoneInfo('Asia/Shanghai'))
```

#### market_today() -> date

返回上海时区下的当前日期。

```python
today = market_today()  # date(2026, 6, 21)
```

#### market_today_str() -> str

返回上海时区下的当前日期字符串，格式 `YYYYMMDD`。

```python
today_str = market_today_str()  # "20260621"
```

### 1.3 时区常量

```python
MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")
```

该常量可在其他地方直接引入使用，保持全项目时区一致。

---

## 2. 数据类型转换 (common/utils/converters.py)

### 2.1 convert_numpy_types(obj: Any) -> Any

递归转换 NumPy 类型为 Python 原生类型，用于 MongoDB 和 JSON 序列化前的数据清理。

**转换规则**：

| 输入类型 | 输出类型 | 示例 |
|---------|---------|------|
| `np.integer` (int64/int32/...) | `int` | `np.int64(42)` -> `42` |
| `np.floating` (float64/float32/...) | `float` | `np.float64(3.14)` -> `3.14` |
| `np.ndarray` | `list` | `np.array([1,2,3])` -> `[1,2,3]` |
| `np.bool_` | `bool` | `np.bool_(True)` -> `True` |
| `pd.isna()` 为 True | `None` | `NaN`, `NaT`, `None` -> `None` |
| `dict` | 递归转换值的 `dict` | |
| `list` | 递归转换元素的 `list` | |

```python
from common.utils.converters import convert_numpy_types

# 实际使用场景：Tushare 返回的数据含 NumPy 类型
data = {"ts_code": "000001.SZ", "close": np.float64(10.75), "vol": np.int64(1234567)}
clean = convert_numpy_types(data)
# {"ts_code": "000001.SZ", "close": 10.75, "vol": 1234567}
```

### 2.2 safe_float(value: Any, default: float = 0.0) -> float

安全转换为 float 类型。

- `None`、`NaN`、`inf` 返回 `default`
- 转换失败返回 `default`

```python
safe_float("3.14")     # 3.14
safe_float(None)       # 0.0
safe_float("abc", -1)  # -1.0
safe_float(float('nan'))  # 0.0  (NaN 检测)
```

### 2.3 safe_int(value: Any, default: int = 0) -> int

安全转换为 int 类型。

```python
safe_int("42")       # 42
safe_int(None)       # 0
safe_int("abc", -1)  # -1
```

---

## 3. 加密工具 (common/utils/crypto.py)

使用 `passlib` 的 `bcrypt` 方案进行密码哈希和验证。

### 3.1 hash_password(password: str) -> str

对明文密码进行 bcrypt 哈希。

```python
from common.utils.crypto import hash_password
hashed = hash_password("my_secure_password")
# $2b$12$...
```

### 3.2 verify_password(plain_password: str, hashed_password: str) -> bool

验证明文密码与哈希值是否匹配。

```python
from common.utils.crypto import verify_password
result = verify_password("my_secure_password", hashed)
# True
result = verify_password("wrong_password", hashed)
# False
```

---

## 4. 数据模型 (common/models/stock.py)

### 4.1 枚举类型

#### MarketType -- 市场类型

| 值 | 说明 |
|----|------|
| `SH` | 上海证券交易所 |
| `SZ` | 深圳证券交易所 |
| `BJ` | 北京证券交易所 |

#### StockStatus -- 股票状态

| 值 | 说明 |
|----|------|
| `L` | Listed - 上市 |
| `D` | Delisted - 退市 |
| `P` | Suspended - 暂停上市 |

### 4.2 Stock -- 股票基本信息

Pydantic BaseModel，包含以下核心字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `ts_code` | `str` | 股票代码，如 `000001.SZ` |
| `symbol` | `str` | 纯数字代码，如 `000001` |
| `name` | `str` | 股票名称 |
| `area` | `Optional[str]` | 地区 |
| `industry` | `Optional[str]` | 所属行业 |
| `fullname` | `Optional[str]` | 全称 |
| `enname` | `Optional[str]` | 英文名称 |
| `market` | `MarketType` | 市场类型 |
| `list_status` | `StockStatus` | 上市状态（默认 LISTED） |
| `list_date` | `Optional[date]` | 上市日期 |
| `delist_date` | `Optional[date]` | 退市日期 |
| `is_hs` | `Optional[str]` | 是否沪深港通标的 |

内置时间戳：`created_at`、`updated_at`（自动设置）。

### 4.3 StockDaily -- 股票日线行情

| 字段 | 类型 | 说明 |
|------|------|------|
| `ts_code` | `str` | 股票代码 |
| `trade_date` | `date` | 交易日期 |
| `open` / `high` / `low` / `close` | `float` | OHLC 数据 |
| `pre_close` | `float` | 昨收价 |
| `change` | `float` | 涨跌额 |
| `pct_chg` | `float` | 涨跌幅 (%) |
| `vol` | `float` | 成交量 (手) |
| `amount` | `float` | 成交额 (千元) |
| `adj_factor` | `Optional[float]` | 复权因子 |
| `ma5` / `ma10` / `ma20` / `ma60` | `Optional[float]` | 均线（由后续计算填充） |

### 4.4 StockFinancial -- 财务数据

包含三大报表（利润表、资产负债表、现金流量表）及财务比率指标：
- 利润表：`revenue`、`operate_profit`、`total_profit`、`net_profit`
- 资产负债表：`total_assets`、`total_liab`、`total_equity`
- 比率：`roe`、`roa`、`debt_ratio`、`gross_margin`、`net_margin`

### 4.5 StockNews -- 新闻舆情

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | `str` | 新闻标题 |
| `content` | `Optional[str]` | 新闻内容 |
| `source` | `Optional[str]` | 来源 |
| `publish_time` | `datetime` | 发布时间 |
| `sentiment` | `Optional[str]` | 情感倾向：positive/negative/neutral |
| `sentiment_score` | `Optional[float]` | 情感得分 [-1, 1] |
| `keywords` | `List[str]` | 关键词列表 |

### 4.6 MarketOverview -- 大盘概览

包含上证/深证指数、涨跌家数、涨跌停家数、成交量/额、热门板块等。

### 4.7 模块懒加载

`common/models/__init__.py` 使用 `__getattr__` 机制实现按需加载，避免 DataSync 导入模型包时顺手带入用户认证相关依赖。使用方式：

```python
from common.models import Stock, StockDaily, StockFinancial  # 按需加载
```

---

## 5. 枚举定义 (common/enums/)

### 5.1 NodeType (common/enums/node.py)

| 值 | 说明 |
|----|------|
| `web` | Web 服务节点 (FastAPI) |
| `data_sync` | 数据同步节点 |
| `mcp` | MCP 协议服务节点 |
| `inference` | AI 推理分析节点 |
| `listener` | 实时市场监听节点 |
| `backtest` | 回测引擎节点 |

### 5.2 TaskType

| 值 | 说明 |
|----|------|
| `stock_analysis` | 股票分析 |
| `market_overview` | 市场概览 |
| `news_sentiment` | 新闻情感分析 |
| `strategy_backtest` | 策略回测 |
| `custom_query` | 自定义查询 |

### 5.3 TaskStatus

| 值 | 说明 |
|----|------|
| `pending` | 等待中 |
| `queued` | 已入队 |
| `running` | 运行中 |
| `completed` | 已完成 |
| `failed` | 已失败 |
| `cancelled` | 已取消 |

### 5.4 SignalType -- 交易信号

| 值 | 含义 |
|----|------|
| `strong_buy` | 强烈买入 |
| `buy` | 买入 |
| `hold` | 持有 |
| `sell` | 卖出 |
| `strong_sell` | 强烈卖出 |

### 5.5 MarketCycle (common/enums/market.py) -- V2 双评分系统周期

| 值 | 周期名 | 条件 |
|----|--------|------|
| `ice_point` | 冰点期 | 双评分 < 20，双走弱/横盘，空仓观望 |
| `recovery` | 修复期 | 20 <= 双评分 < 40，双走强，轻仓试错 |
| `main_upward` | 主升期 | 双评分 >= 60，双走强/横盘，重仓做多 |
| `divergence` | 分歧期 | 评分背离或趋势背离，半仓龙头 |
| `decline` | 退潮期 | 双评分 < 40，双走弱，空仓等待 |
| `chaos` | 混沌期 | 无明确周期，轮动观望 |
| `unknown` | 未知 | 数据不足 |

兼容旧枚举值：`incubation`（已合并到 recovery）、`rotation`（已合并到 divergence）。

### 5.6 ThemeStatus -- 板块状态

| 值 | 含义 |
|----|------|
| `main_theme` | 当前主线 |
| `strong_focus` | 强势关注 |
| `rising` | 上升中 |
| `rotating` | 轮动中 |
| `fading` | 衰退中 |
| `normal` | 普通 |

### 5.7 TradeDirection (common/enums/trade.py)

| 值 | 说明 |
|----|------|
| `buy` | 买入 |
| `sell` | 卖出 |
| `hold` | 持有 |

### 5.8 StrategyType -- 监听策略类型

共 13 种策略类型，包括：市场指数预警、涨跌停打开、涨跌幅阈值、分钟异动、撑压线、固定/移动止损、放量突破、均线交叉、5日线低吸、自定义等。

### 5.9 回测枚举 (common/enums/backtest.py)

#### UniverseType -- 股票池
| 值 | 说明 |
|----|------|
| `all_a` | 全A股 |

#### ExcludeRule -- 排除规则
| 值 | 说明 |
|----|------|
| `st` | ST 股票 |
| `new_stock` | 次新股（上市不满1年） |
| `limit_up` | 涨停股（一字板） |
| `limit_down` | 跌停股 |

#### FactorCategory -- 因子分类
`momentum`（动量）、`value`（价值）、`quality`（质量）、`growth`（成长）、`volatility`（波动）、`liquidity`（流动性）、`technical`（技术）。

---

## 6. 结构化日志 (common/logger/)

### 6.1 Loki 日志集成 (loki_logger.py)

#### Trace ID 管理

使用 Python `contextvars` 实现请求级 trace_id 传递：

```python
from common.logger import get_trace_id, set_trace_id, TraceContext

# 获取当前 trace_id（无则自动生成）
tid = get_trace_id()

# 手动设置
set_trace_id("custom-trace-id")

# 上下文管理器（自动恢复）
with TraceContext() as tid:
    logger.info("Processing request")
    # 离开 with 块后自动恢复原 trace_id
```

#### JsonFormatter

输出 JSON 格式日志，适配 Loki/Grafana 查询：

```json
{
  "timestamp": "2026-06-21T14:30:00+08:00",
  "level": "INFO",
  "logger": "collector.stock_daily",
  "message": "Bulk write completed",
  "service": "stock-agent",
  "module": "collector",
  "function": "_write_buffer",
  "line": 312,
  "trace_id": "a1b2c3d4-...",
  "extra": {...}
}
```

#### LokiHandler

异步发送日志到 Loki，支持批量缓冲。若 `logging_loki` 库未安装则降级到 stderr。

#### StockAgentLogger

继承 `logging.Logger`，自动注入 `trace_id`。已通过 `logging.setLoggerClass(StockAgentLogger)` 设置为全局 Logger 类。

#### get_logger(name, level, service_name) -> Logger

获取统一配置的 Logger 实例：

```python
from common.logger import get_logger
logger = get_logger(__name__)
```

- 自动添加 `JsonFormatter` 控制台 Handler
- 缓存已创建的 logger 实例，避免重复创建

#### setup_loki_handler(logger, loki_url, service_name, extra_labels)

为 Logger 添加 Loki Handler。

#### log_execution_time() 装饰器

记录函数执行时间：

```python
@log_execution_time()
async def my_function():
    pass
# 输出: my_function completed | duration_ms=123.45
```

自动检测 async/sync 函数并选择合适的包装方式。

### 6.2 结构化日志工具 (structured.py)

#### sanitize_log_value(value, max_value_chars, max_items, max_depth)

压缩日志值，防止日志过大。支持 `Mapping`、`list/tuple/set/frozenset`、`str`、基本类型。截断策略：

| 值类型 | 截断策略 |
|--------|---------|
| `str` | 超过 `max_value_chars` 字符截断，附原长度 |
| `Mapping` (dict) | 保留前 `max_items` 个 key-value 对 |
| `list/tuple/set` | 保留前 `max_items` 个元素 |
| 嵌套结构 | `max_depth` 递归深度限制 |

默认限制：`max_value_chars=500`, `max_items=5`, `max_depth=2`。

#### build_log_extra(**fields) -> dict

构建日志 `extra` 字典，自动应用 sanitize 裁剪。从 `ObservabilitySettings` 读取配置限制。

```python
extra = build_log_extra(
    job="stock_daily",
    count=5000,
    sample_data=large_dict,  # 自动裁剪
)
logger.info("Processing", extra=extra)
```

#### format_log_fields(**fields) -> str

格式化键值对为文本字符串，用于 Docker 纯文本日志。

```python
text = format_log_fields(job="stock_daily", count=5000)
# "job=stock_daily count=5000"
```

#### log_event(logger, level, event, **fields)

统一的紧凑文本 + 结构化字段日志输出：

```python
log_event(logger, logging.WARNING, "datasync_validation_dropped_records",
    job="stock_daily", collection="stock_daily", bad_count=5, total_count=1000)
# 输出: datasync_validation_dropped_records job=stock_daily collection=stock_daily bad_count=5 total_count=1000
# 同时 extra 中包含结构化 fields
```
