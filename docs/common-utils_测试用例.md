# 公共工具与模型模块 测试用例

## 1. market_now 时区正确性（Asia/Shanghai）

### TC-TIME-001: market_now() 返回上海时区当前时间

| 项目 | 内容 |
|------|------|
| **测试目标** | `market_now()` 无参数时返回 Asia/Shanghai 时区的当前时间 |
| **步骤** | 1. 调用 `market_now()`<br>2. 检查 `.tzinfo` |
| **预期结果** | `result.tzinfo == ZoneInfo("Asia/Shanghai")` |

### TC-TIME-002: market_now() 与系统 UTC 时间差

| 项目 | 内容 |
|------|------|
| **测试目标** | 上海时间比 UTC 快 8 小时 |
| **步骤** | 1. 调用 `market_now()` 获取上海时间<br>2. 调用 `datetime.now(timezone.utc)` 获取 UTC 时间<br>3. 计算时间差 |
| **预期结果** | 时差约为 8 小时（`cn_time.hour - utc_time.hour` 约等于 8，考虑分钟进位） |

### TC-TIME-003: market_now() 转换 UTC 时间

| 项目 | 内容 |
|------|------|
| **测试目标** | 传入 UTC datetime 时正确转换到上海时区 |
| **步骤** | 1. `utc = datetime(2026, 6, 21, 6, 30, tzinfo=timezone.utc)`<br>2. 调用 `market_now(utc)` |
| **预期结果** | `result.hour == 14`, `result.minute == 30`, `result.tzinfo == ZoneInfo("Asia/Shanghai")` |

### TC-TIME-004: market_now() 传入无时区 datetime

| 项目 | 内容 |
|------|------|
| **测试目标** | 传入无时区 datetime 时附加上海时区（不改变数值） |
| **步骤** | 1. `naive = datetime(2026, 6, 21, 14, 30)`<br>2. 调用 `market_now(naive)` |
| **预期结果** | `result.hour == 14`, `result.minute == 30`, `result.tzinfo == ZoneInfo("Asia/Shanghai")`。注意：此处不做时间转换，只附加时区 |

### TC-TIME-005: 北京时间跨零点

| 项目 | 内容 |
|------|------|
| **测试目标** | 北京时间零点前后 `market_today()` 返回正确日期 |
| **前置条件** | 模拟系统时间为北京时间 `2026-06-21 23:59:00` 和 `2026-06-22 00:01:00` |
| **步骤** | 1. 设置北京时间 23:59 调用 `market_today()`<br>2. 设置北京时间 00:01 调用 `market_today()` |
| **预期结果** | 23:59 返回 `date(2026, 6, 21)`；00:01 返回 `date(2026, 6, 22)` |

---

## 2. market_today_str 格式验证

### TC-FMT-001: market_today_str 返回 YYYYMMDD 格式

| 项目 | 内容 |
|------|------|
| **测试目标** | 返回值格式为 8 位数字字符串 |
| **步骤** | 1. 调用 `market_today_str()`<br>2. 检查长度和字符 |
| **预期结果** | `len(result) == 8`, `result.isdigit() == True`, 格式如 `"20260621"` |

### TC-FMT-002: market_today_str 与 market_today 一致

| 项目 | 内容 |
|------|------|
| **测试目标** | 两个函数返回同一天的日期 |
| **步骤** | 1. `s = market_today_str()`<br>2. `d = market_today()`<br>3. `d2 = date(int(s[:4]), int(s[4:6]), int(s[6:8]))` |
| **预期结果** | `d == d2` |

---

## 3. 交易日/非交易日判断

### TC-TRADE-001: 工作日判断（无日历降级）

| 项目 | 内容 |
|------|------|
| **测试目标** | 交易日历获取失败时降级为周一至周五 |
| **前置条件** | 模拟 `get_trade_calendar` 抛出异常 |
| **步骤** | 1. 调用 `BaseCollector._get_trade_dates("20260615", "20260621")`<br>2. 模拟异常降级 |
| **预期结果** | 返回 `["20260615"(一), "20260616"(二), "20260617"(三), "20260618"(四), "20260619"(五)]`，不包含 20260620(六)、20260621(日) |

### TC-TRADE-002: 市场时间在上海时区

| 项目 | 内容 |
|------|------|
| **测试目标** | 即使系统在 UTC 时区，`market_today_str()` 返回的仍是北京时间日期 |
| **前置条件** | 系统时区设为 UTC |
| **步骤** | 1. UTC 时间为 `2026-06-21 20:00`（北京时间 6/22 04:00）<br>2. 调用 `market_today_str()` |
| **预期结果** | 返回 `"20260622"`（北京时间日期），而非 `"20260621"`（UTC日期） |

---

## 4. 数据模型序列化/反序列化

### TC-MODEL-001: Stock 模型创建与验证

| 项目 | 内容 |
|------|------|
| **测试目标** | 使用正确数据创建 Stock 实例 |
| **步骤** | 1. 创建 `Stock(ts_code="000001.SZ", symbol="000001", name="平安银行", market=MarketType.SZ)`<br>2. 检查必填字段 |
| **预期结果** | `stock.ts_code == "000001.SZ"`, `stock.symbol == "000001"`, `stock.market == MarketType.SZ`, `stock.list_status == StockStatus.LISTED` (默认值) |

### TC-MODEL-002: Stock 模型缺少必填字段抛出 ValidationError

| 项目 | 内容 |
|------|------|
| **测试目标** | 缺少 `ts_code` 时 Pydantic 验证失败 |
| **步骤** | 1. 尝试 `Stock(name="test", symbol="000001", market=MarketType.SH)` |
| **预期结果** | 抛出 `pydantic.ValidationError`，提示 `ts_code` 为必填字段 |

### TC-MODEL-003: Stock 模型序列化为 JSON

| 项目 | 内容 |
|------|------|
| **测试目标** | `model_dump(mode="json")` 正确序列化 |
| **步骤** | 1. 创建 Stock 实例<br>2. 调用 `stock.model_dump(mode="json")` |
| **预期结果** | JSON dict 包含 `ts_code`, `symbol`, `name`, `market`, `list_status` 等字段，`created_at` 和 `updated_at` 为 ISO 格式字符串 |

### TC-MODEL-004: StockDaily 模型创建与字段类型验证

| 项目 | 内容 |
|------|------|
| **测试目标** | StockDaily 的数值字段正确转换 |
| **步骤** | 1. 创建 `StockDaily(ts_code="000001.SZ", trade_date=date(2026,6,19), open=10.5, high=10.8, low=10.4, close=10.75, pre_close=10.45, change=0.30, pct_chg=2.87, vol=1234567.0, amount=132456.78)`<br>2. 检查类型 |
| **预期结果** | 所有 float 字段保持 float 类型，`trade_date` 为 `date` 类型，`ts_code` 为 `str` |

### TC-MODEL-005: StockDaily 可选字段默认值

| 项目 | 内容 |
|------|------|
| **测试目标** | 不提供均线字段时的默认值为 None |
| **步骤** | 1. 创建最小 StockDaily 实例<br>2. 检查 `ma5`, `ma10`, `ma20`, `ma60`, `adj_factor` |
| **预期结果** | 所有值为 `None` |

### TC-MODEL-006: MarketType 枚举字符串值

| 项目 | 内容 |
|------|------|
| **测试目标** | MarketType 枚举值正确 |
| **步骤** | 1. 检查 `MarketType.SH.value`<br>2. 检查 `MarketType.SZ.value`<br>3. 检查 `MarketType.BJ.value`<br>4. 尝试 `MarketType("SH")` 反序列化 |
| **预期结果** | `"SH"`, `"SZ"`, `"BJ"`, 反序列化成功返回 `MarketType.SH` |

### TC-MODEL-007: Stock model_dump 排除默认值（exclude_unset）

| 项目 | 内容 |
|------|------|
| **测试目标** | `model_dump(exclude_unset=True)` 只输出设定的字段 |
| **步骤** | 1. 创建 `Stock(ts_code="000001.SZ", symbol="000001", name="平安银行", market=MarketType.SZ)`<br>2. 调用 `stock.model_dump(exclude_unset=True)` |
| **预期结果** | 只包含 `ts_code`, `symbol`, `name`, `market` 这 4 个字段，不含 `area`, `industry` 等可选字段 |

---

## 5. 枚举值唯一性与完整性

### TC-ENUM-001: NodeType 枚举值唯一性

| 项目 | 内容 |
|------|------|
| **测试目标** | 所有 NodeType 枚举值不重复 |
| **步骤** | 收集所有成员的 `.value`，检查重复 |
| **预期结果** | 6 个值全部唯一：`{"web", "data_sync", "mcp", "inference", "listener", "backtest"}` |

### TC-ENUM-002: TaskStatus 状态流转完整性

| 项目 | 内容 |
|------|------|
| **测试目标** | TaskStatus 覆盖任务全生命周期状态 |
| **步骤** | 检查是否包含：等待、入队、运行、完成、失败、取消 |
| **预期结果** | 包含 `pending`, `queued`, `running`, `completed`, `failed`, `cancelled` |

### TC-ENUM-003: MarketCycle 枚举值数量与映射

| 项目 | 内容 |
|------|------|
| **测试目标** | MarketCycle 包含 7 个活跃值 + 2 个兼容值 |
| **步骤** | 列出所有枚举成员 |
| **预期结果** | 活跃值：`ice_point`, `recovery`, `main_upward`, `divergence`, `decline`, `chaos`, `unknown`。兼容值：`incubation`, `rotation` |

### TC-ENUM-004: SignalType 信号方向完整性

| 项目 | 内容 |
|------|------|
| **测试目标** | 交易信号覆盖从强买到强卖的 5 个级别 |
| **步骤** | 检查所有 SignalType 值 |
| **预期结果** | `strong_buy`, `buy`, `hold`, `sell`, `strong_sell` 五个级别由多到空对称 |

### TC-ENUM-005: StrategyType 策略类型数量

| 项目 | 内容 |
|------|------|
| **测试目标** | StrategyType 包含 13 种策略 |
| **步骤** | `len(StrategyType)` |
| **预期结果** | `13` |

### TC-ENUM-006: FactorCategory 7 大因子分类

| 项目 | 内容 |
|------|------|
| **测试目标** | 因子分类覆盖完整的量化因子体系 |
| **步骤** | 列出所有成员 |
| **预期结果** | `momentum`, `value`, `quality`, `growth`, `volatility`, `liquidity`, `technical` |

### TC-ENUM-007: 枚举值序列化/反序列化一致性

| 项目 | 内容 |
|------|------|
| **测试目标** | 所有 str 枚举支持 `EnumClass(value)` 反序列化 |
| **步骤** | 对每个 `str, Enum` 类型的枚举，用 `.value` 反序列化，验证一致性 |
| **预期结果** | `NodeType(NodeType.WEB.value) == NodeType.WEB` 对所有枚举成立 |

---

## 6. 结构化日志写入

### TC-LOG-001: get_logger 创建并缓存 Logger

| 项目 | 内容 |
|------|------|
| **测试目标** | 同名 logger 返回同一实例 |
| **步骤** | 1. `logger1 = get_logger("test.module")`<br>2. `logger2 = get_logger("test.module")` |
| **预期结果** | `logger1 is logger2 == True` |

### TC-LOG-002: get_logger 输出 JSON 格式

| 项目 | 内容 |
|------|------|
| **测试目标** | Logger 输出为 JSON 格式（JsonFormatter） |
| **前置条件** | 捕获 stdout |
| **步骤** | 1. 创建 logger<br>2. `logger.info("test message")`<br>3. 解析捕获的输出为 JSON |
| **预期结果** | JSON 包含 `timestamp`, `level`, `logger`, `message`, `service`, `trace_id` 等字段 |

### TC-LOG-003: TraceContext 上下文管理

| 项目 | 内容 |
|------|------|
| **测试目标** | `TraceContext` 在 with 块内设置 trace_id，离开后恢复 |
| **步骤** | 1. 获取当前 trace_id `tid_before = get_trace_id()`<br>2. `with TraceContext("custom-trace-123") as tid:` 检查 `get_trace_id()`<br>3. 离开 with 块后检查 `get_trace_id()` |
| **预期结果** | with 块内 `tid == "custom-trace-123"`，离开后 `get_trace_id() == tid_before` |

### TC-LOG-004: set_trace_id 手动设置

| 项目 | 内容 |
|------|------|
| **测试目标** | 手动设置 trace_id 后 get_trace_id 返回正确值 |
| **步骤** | 1. `set_trace_id("manual-trace-id")`<br>2. `get_trace_id()` |
| **预期结果** | `"manual-trace-id"` |

### TC-LOG-005: sanitize_log_value 字符串截断

| 项目 | 内容 |
|------|------|
| **测试目标** | 超过 max_value_chars 的字符串被截断 |
| **步骤** | 1. `long_str = "a" * 600`<br>2. `result = sanitize_log_value(long_str, max_value_chars=100)` |
| **预期结果** | `result` 以 `"a"*100` 开头，以 `...<truncated:600>` 结尾 |

### TC-LOG-006: sanitize_log_value dict 条目限制

| 项目 | 内容 |
|------|------|
| **测试目标** | dict 超过 max_items 时只保留前 N 个条目 |
| **步骤** | 1. `big_dict = {f"key{i}": i for i in range(20)}`<br>2. `result = sanitize_log_value(big_dict, max_items=5)` |
| **预期结果** | `len(result) == 6`（5 个条目 + 1 个 `_truncated_items: 15`） |

### TC-LOG-007: sanitize_log_value list 条目限制

| 项目 | 内容 |
|------|------|
| **测试目标** | list 超过 max_items 时保留前 N 个元素 |
| **步骤** | 1. `big_list = list(range(100))`<br>2. `result = sanitize_log_value(big_list, max_items=3)` |
| **预期结果** | 结果包含 `[0, 1, 2, {"_truncated_items": 97}]` |

### TC-LOG-008: sanitize_log_value 嵌套深度限制

| 项目 | 内容 |
|------|------|
| **测试目标** | 超过 max_depth 的结构返回类型名 |
| **步骤** | 1. `deep = {"a": {"b": {"c": {"d": "value"}}}}`<br>2. `result = sanitize_log_value(deep, max_depth=2)` |
| **预期结果** | 第三层嵌套返回 `"<dict>"` 类型名 |

### TC-LOG-009: log_event 输出结构化事件

| 项目 | 内容 |
|------|------|
| **测试目标** | `log_event` 产生结构化的日志记录 |
| **前置条件** | 使用带 MemoryHandler 的 logger 捕获记录 |
| **步骤** | 1. `log_event(logger, logging.WARNING, "test_event", key1="val1", key2=42)`<br>2. 检查日志记录的 message 和 extra |
| **预期结果** | `record.message` 包含 `"test_event key1=val1 key2=42"`，`record.extra_data` 包含 `{"event": "test_event", "key1": "val1", "key2": 42}` |

### TC-LOG-010: build_log_extra 自动裁剪

| 项目 | 内容 |
|------|------|
| **测试目标** | `build_log_extra` 自动应用尺寸限制 |
| **步骤** | 1. `extra = build_log_extra(data={"x"*600: i for i in range(20)})`<br>2. 检查 extra_data 结构 |
| **预期结果** | 值被截断到默认 500 字符，dict 只保留前 5 个条目 |

---

## 7. 转换器边界情况

### TC-CONV-001: convert_numpy_types 处理 None 值

| 项目 | 内容 |
|------|------|
| **测试目标** | None 输入直接返回 None |
| **步骤** | `convert_numpy_types(None)` |
| **预期结果** | `None` |

### TC-CONV-002: convert_numpy_types 处理混合嵌套结构

| 项目 | 内容 |
|------|------|
| **测试目标** | 深层嵌套 dict+list 中的 NumPy 类型被正确转换 |
| **步骤** | 1. `data = {"items": [{"val": np.float64(1.5)}, {"val": np.int64(3)}]}`<br>2. `convert_numpy_types(data)` |
| **预期结果** | `{"items": [{"val": 1.5}, {"val": 3}]}` （全部 Python 原生类型） |

### TC-CONV-003: convert_numpy_types 处理 pd.NaT 和 pd.NA

| 项目 | 内容 |
|------|------|
| **测试目标** | Pandas 缺失值转换为 None |
| **步骤** | 1. `convert_numpy_types(pd.NaT)`<br>2. `convert_numpy_types(float('nan'))` |
| **预期结果** | 均为 `None` |

### TC-CONV-004: convert_numpy_types 处理空容器

| 项目 | 内容 |
|------|------|
| **测试目标** | 空 dict、空 list 不被修改 |
| **步骤** | `convert_numpy_types({})`, `convert_numpy_types([])` |
| **预期结果** | `{}`, `[]` |

### TC-CONV-005: safe_float 边界情况

| 项目 | 内容 |
|------|------|
| **测试目标** | 各类非法输入返回默认值 |
| **步骤** | 1. `safe_float(None)`<br>2. `safe_float("abc")`<br>3. `safe_float(float('inf'))`<br>4. `safe_float("")`<br>5. `safe_float("3.14")` |
| **预期结果** | `0.0`, `0.0`, `0.0`, `0.0`, `3.14` |

### TC-CONV-006: safe_int 边界情况

| 项目 | 内容 |
|------|------|
| **测试目标** | 各类非法输入返回默认值 |
| **步骤** | 1. `safe_int(None)`<br>2. `safe_int("abc")`<br>3. `safe_int("3.9")`（先 float 再 int）<br>4. `safe_int(3.9)`<br>5. `safe_int("42")` |
| **预期结果** | `0`, `0`, `3`, `3`, `42` |

### TC-CONV-007: 空字符串和空白字符串

| 项目 | 内容 |
|------|------|
| **测试目标** | 空字符串在保存到数据库前的处理 |
| **步骤** | 在 validation 层面检查 `""` 被当作缺失处理 |
| **预期结果** | `""` 在 `_validate_records_with_dead_letters` 的 `required` 检查中触发 `missing_required` 错误 |

### TC-CONV-008: hash_password 和 verify_password 一致性

| 项目 | 内容 |
|------|------|
| **测试目标** | 哈希和验证的正确性 |
| **步骤** | 1. `h = hash_password("test_password")`<br>2. `verify_password("test_password", h)`<br>3. `verify_password("wrong_password", h)` |
| **预期结果** | 验证正确密码返回 `True`，错误密码返回 `False` |

### TC-CONV-009: hash_password 每次生成不同哈希

| 项目 | 内容 |
|------|------|
| **测试目标** | bcrypt 每次生成不同的盐值和哈希 |
| **步骤** | `h1 = hash_password("same_pwd")`, `h2 = hash_password("same_pwd")` |
| **预期结果** | `h1 != h2`（因为盐不同），但 `verify_password("same_pwd", h1)` 和 `verify_password("same_pwd", h2)` 均为 `True` |

---

## 代码走查验证结果

**走查日期**: 2026-06-21 | **方法**: 代码走查 | **结果**: 39/41 通过，2 处代码不一致

| 用例 | 结果 | 走查依据 |
|------|------|----------|
| TC-TIME-001~005 | ✅ PASS | `market_now()` (market_time.py:14-20): UTC→CST 转换，naive dt attach 时区。`market_today()` (line 23-25) |
| TC-FMT-001~002 | ✅ PASS | `market_today_str()` (line 28-30): `%Y%m%d` 8 位数字 |
| TC-TRADE-001~002 | ✅ PASS | `_get_trade_dates` (collector.py:128-158): 异常降级→工作日列表 |
| TC-MODEL-001~007 | ✅ PASS | 所有模型为 Pydantic BaseModel，必填/可选字段正确，枚举 str,Enum 支持 |
| TC-ENUM-001~007 | ✅ PASS | 7 组枚举均继承 str,Enum，值唯一，成员数正确 |
| TC-LOG-001~010 | ✅ PASS | `get_logger` 缓存 (loki_logger.py:205,224)，JsonFormatter (line 65-106)，TraceContext (line 41-62)，`sanitize_log_value` 截断 (structured.py:40-75)，`log_event` (line 112-124) |
| TC-CONV-001~004 | ✅ PASS | `convert_numpy_types` (converters.py:31-44): None→None，递归处理 dict/list，NaT→None |
| TC-CONV-005 | ⚠️ 不一致 | `common/utils/converters.py` 的 `safe_float` 仅检查 `np.isnan`，不检查 `math.isinf`，`float('inf')` 返回 `inf` 而非 `0.0`。对比 `core/base/collector.py:567-574` 的 `_safe_float` 正确检查 `math.isinf` |
| TC-CONV-006 | ⚠️ 不一致 | `common/utils/converters.py` 的 `safe_int` 直接调用 `int(value)`，`safe_int("3.9")` 抛出 ValueError 返回 0。对比 `core/base/collector.py:577-582` 的 `_safe_int` 使用 `int(float(value))` 正确返回 3 |
| TC-CONV-007~009 | ✅ PASS | 必填字段检查 (collector.py:402-405)，bcrypt `hash_password`/`verify_password` (crypto.py:13-20)，每次哈希唯一 |
