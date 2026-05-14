"""
Listener 节点

负责:
- 实时行情监听 (60秒轮询)
- 策略触发检测
- 企业微信预警推送
"""

import asyncio
from typing import Optional, List, Dict, Any, Iterable
from datetime import datetime, date, time
import uuid
import logging

from core.base import BaseNode
from core.protocols import (
    NodeType,
    StrategySubscription,
    StrategyAlert,
    MarketSnapshot,
    StrategyType,
)
from core.settings import settings
from core.managers import (
    redis_manager,
    mongo_manager,
    data_source_manager,
)
from core.managers.notification_manager import notification_manager
from common.utils import market_now, market_today_str

from .strategies import (
    BaseStrategy,
    LimitOpenStrategy,
    PriceChangeStrategy,
    IntradayPriceMoveStrategy,
    MarketIndexAlertStrategy,
    MA5BuyStrategy,
    SupportResistanceStrategy,
    FixedStopLossStrategy,
    TrailingStopLossStrategy,
    PositionPnlStrategy,
    PositionIntradayPnlStrategy,
)


class ListenerNode(BaseNode):
    """
    Listener 节点
    
    职责:
    1. 每 60 秒轮询实时行情
    2. 每日 9:15 获取涨跌停价格
    3. 遍历活跃策略，检测触发条件
    4. 推送企业微信预警
    
    非交易时间自动静默，节省 API 消耗。
    """
    
    node_type = NodeType.LISTENER
    DEFAULT_RPC_PORT = 50053  # ListenerNode 默认 RPC 端口
    
    def __init__(self, node_id: Optional[str] = None, rpc_port: int = 0):
        super().__init__(node_id, rpc_port or settings.rpc.listener_port)
        self.logger = logging.getLogger(f"node.listener.{self.node_id}")
        
        # 配置
        self._config = settings.listener
        self._poll_interval = self._config.poll_interval
        
        # 状态
        self._current_snapshot: Optional[MarketSnapshot] = None
        self._previous_snapshot: Optional[MarketSnapshot] = None
        self._limit_stocks: Dict[str, Dict[str, Any]] = {}  # 今日涨跌停价格
        self._last_limit_fetch_date: Optional[str] = None
        
        # 策略执行器
        self._strategies: Dict[str, BaseStrategy] = {}
        self._subscriptions: List[StrategySubscription] = []
        
        # 任务
        self._poll_task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """启动节点"""
        self.logger.info("Starting Listener node...")
        
        # 初始化 Managers
        await redis_manager.initialize()
        await mongo_manager.initialize()
        await data_source_manager.initialize()
        await notification_manager.initialize()
        
        # 启动 RPC 服务器
        await self._start_rpc_server()
        
        # 注册策略执行器
        self._register_strategies()
        
        # 加载策略订阅配置
        await self._load_subscriptions()
        
        self.logger.info(
            f"Listener started: poll_interval={self._poll_interval}s, "
            f"strategies={len(self._strategies)}, subscriptions={len(self._subscriptions)}, "
            f"rpc={self._rpc_address}"
        )
    
    async def stop(self) -> None:
        """停止节点"""
        self.logger.info("Stopping Listener node...")
        
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        
        self.logger.info("Listener node stopped")
    
    async def run(self) -> None:
        """节点主循环"""
        self.logger.info("Starting polling loop...")
        
        while self._running:
            try:
                # 生成 trace_id
                trace_id = uuid.uuid4().hex
                self.set_trace_id(trace_id)
                
                # 检查是否为交易时间
                if self._config.silent_outside_trading:
                    is_trading = await self._is_trading_time()
                    if not is_trading:
                        self.logger.debug("Outside trading hours, sleeping...")
                        await asyncio.sleep(self._poll_interval)
                        continue
                
                # 执行轮询
                await self._poll_cycle(trace_id)
                
            except Exception as e:
                self.logger.error(f"Poll cycle error: {e}", exc_info=True)
            finally:
                self.clear_trace_id()
            
            # 等待下一次轮询
            await asyncio.sleep(self._poll_interval)
    
    # ==================== RPC 方法 ====================
    
    def _register_rpc_methods(self) -> None:
        """注册 RPC 方法"""
        super()._register_rpc_methods()
        
        # 刷新策略订阅
        self.register_rpc_method("refresh_strategies", self._handle_refresh_strategies)
        
        self.logger.info("Registered RPC methods: ping, refresh_strategies")
    
    async def _handle_refresh_strategies(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        RPC: 刷新策略订阅配置
        
        当 WebNode 修改策略后，通过 RPC 通知 ListenerNode 刷新。
        """
        trace_id = params.get("_trace_id", "-")
        strategy_type = params.get("strategy_type")  # 可选，指定刷新特定策略
        
        self.logger.info(f"[{trace_id}] RPC: refresh_strategies, type={strategy_type}")
        
        try:
            # 重新加载订阅配置
            await self._load_subscriptions()
            
            return {
                "status": "ok",
                "subscriptions_count": len(self._subscriptions),
                "message": f"Refreshed {len(self._subscriptions)} subscriptions",
            }
        except Exception as e:
            self.logger.error(f"[{trace_id}] Failed to refresh strategies: {e}")
            return {
                "status": "error",
                "message": str(e),
            }
    
    # ==================== 策略管理 ====================
    
    def _register_strategies(self) -> None:
        """注册内置策略执行器"""
        self._strategies = {
            StrategyType.MARKET_INDEX_ALERT.value: MarketIndexAlertStrategy(),
            StrategyType.LIMIT_OPEN.value: LimitOpenStrategy(),
            StrategyType.PRICE_CHANGE.value: PriceChangeStrategy(),
            StrategyType.INTRADAY_PRICE_MOVE.value: IntradayPriceMoveStrategy(),
            StrategyType.MA5_BUY.value: MA5BuyStrategy(),
            StrategyType.SUPPORT_RESISTANCE.value: SupportResistanceStrategy(),
            StrategyType.FIXED_STOP_LOSS.value: FixedStopLossStrategy(),
            StrategyType.TRAILING_STOP_LOSS.value: TrailingStopLossStrategy(),
            StrategyType.POSITION_PNL.value: PositionPnlStrategy(),
            StrategyType.POSITION_INTRADAY_PNL.value: PositionIntradayPnlStrategy(),
        }
        self.logger.info(f"Registered strategies: {list(self._strategies.keys())}")
    
    async def _load_subscriptions(self) -> None:
        """从 MongoDB 加载策略订阅配置"""
        try:
            records = await mongo_manager.find_many(
                "strategy_subscriptions",
                {"is_active": True},
            )
            
            self._subscriptions = []
            for record in records:
                # 移除 MongoDB 的 _id 字段
                record.pop("_id", None)
                try:
                    sub = StrategySubscription(**record)
                    self._subscriptions.append(sub)
                except Exception as e:
                    self.logger.warning(f"Skip invalid subscription: {e}")
            
            self.logger.info(f"Loaded {len(self._subscriptions)} active subscriptions")
            for sub in self._subscriptions:
                self.logger.info(
                    f"  - {sub.strategy_name}: type={sub.strategy_type.value}, "
                    f"watch_list={sub.watch_list[:3]}{'...' if len(sub.watch_list) > 3 else ''}"
                )
            
        except Exception as e:
            self.logger.error(f"Failed to load subscriptions: {e}")
            self._subscriptions = []
    
    async def reload_subscriptions(self) -> None:
        """
        重新加载订阅配置
        
        可在运行时通过 API 调用以支持动态更新。
        """
        await self._load_subscriptions()
        self.logger.info("Subscriptions reloaded")
    
    # ==================== 轮询逻辑 ====================
    
    async def _poll_cycle(self, trace_id: str) -> None:
        """
        单次轮询循环
        
        1. 检查是否需要获取涨跌停价格
        2. 获取三大指数实时行情
        3. 获取个股实时行情
        4. 构建市场快照
        5. 统计并存储实时市场数据到 Redis
        6. 执行策略检测
        7. 发送预警
        """
        self.logger.info(f"[poll] trace_id={trace_id} | Starting poll cycle")
        
        # 1. 每日获取涨跌停价格 (9:15)
        await self._fetch_limit_prices_if_needed()
        
        # 2. 获取三大指数实时行情
        index_quotes, index_source = await data_source_manager.get_realtime_index_quotes()
        
        # 3. 获取需要监听的股票列表
        watch_codes = await self._get_all_watch_codes()
        if not watch_codes:
            self.logger.warning(
                f"No stocks to watch, skipping. "
                f"subscriptions={len(self._subscriptions)}, limit_stocks={len(self._limit_stocks)}"
            )
            return
        
        self.logger.info(f"[poll] Watching {len(watch_codes)} stocks")
        
        # 4. 获取实时行情 (分批获取，每批50只)
        self.logger.info(f"[poll] Fetching realtime quotes for {len(watch_codes)} stocks...")
        quotes, quote_source = await data_source_manager.get_realtime_quotes(
            watch_codes,
            batch_size=50,
        )
        if not quotes:
            self.logger.warning("Failed to get realtime quotes")
            return
        
        self.logger.info(
            f"[poll] Quote sources: stocks={quote_source or '-'}, indexes={index_source or '-'}"
        )
        
        # 5. 构建市场快照
        self._previous_snapshot = self._current_snapshot
        self._current_snapshot = self._build_snapshot(quotes)
        
        self.logger.info(
            f"[poll] Snapshot: total={self._current_snapshot.total_stocks}, "
            f"up={self._current_snapshot.up_count}, down={self._current_snapshot.down_count}"
        )
        
        # 6. 存储实时市场数据到 Redis (供 Web 节点使用)
        await self._store_realtime_market_data(index_quotes)
        
        # 7. 统计封板情况（调试用）
        limit_up_stocks = []
        limit_down_stocks = []
        for ts_code, quote in self._current_snapshot.quotes.items():
            limit_info = self._limit_stocks.get(ts_code, {})
            current_price = quote.get("price", 0)
            up_limit = limit_info.get("up_limit", 0)
            down_limit = limit_info.get("down_limit", 0)
            
            if up_limit and current_price and abs(current_price - up_limit) < 0.01:
                limit_up_stocks.append(f"{ts_code}({quote.get('name', '')})")
            elif down_limit and current_price and abs(current_price - down_limit) < 0.01:
                limit_down_stocks.append(f"{ts_code}({quote.get('name', '')})")
        
        if limit_up_stocks or limit_down_stocks:
            self.logger.info(
                f"[poll] 封板统计: 涨停={len(limit_up_stocks)}, 跌停={len(limit_down_stocks)}"
            )
            if limit_up_stocks[:5]:
                self.logger.info(f"[poll] 涨停股(前5): {', '.join(limit_up_stocks[:5])}")
            if limit_down_stocks[:5]:
                self.logger.info(f"[poll] 跌停股(前5): {', '.join(limit_down_stocks[:5])}")
        
        # 8. 执行策略检测
        alerts = await self._evaluate_strategies()
        
        self.logger.info(f"[poll] Strategy evaluation done, alerts={len(alerts)}")
        
        if alerts:
            # 9. 发送预警
            for alert in alerts:
                self.logger.info(
                    f"[poll] Sending alert: {alert.ts_code} - {alert.trigger_reason}"
                )
                await self._process_alert(alert)
    
    async def _fetch_limit_prices_if_needed(self) -> None:
        """
        获取今日涨跌停价格 (每日一次)
        
        在交易日 9:15 后获取。
        """
        today = market_today_str()
        
        # 已经获取过今日数据
        if self._last_limit_fetch_date == today:
            return
        
        # 检查时间 (9:15 后才有数据)
        now = market_now()
        fetch_time = self._parse_time(self._config.limit_fetch_time)
        if now.time() < fetch_time:
            self.logger.debug(f"Before limit fetch time ({self._config.limit_fetch_time}), skipping")
            return
        
        self.logger.info(f"Fetching limit prices for {today}...")
        
        try:
            limit_data, limit_source = await data_source_manager.get_stk_limit(trade_date=today)
            
            if limit_data:
                original_count = len(limit_data)
                
                # 从数据库获取有效股票列表
                valid_stocks = await self._get_valid_stocks_from_db()
                
                # 过滤: 仅保留数据库中存在且非ST的股票
                self._limit_stocks = {}
                filtered_count = 0
                st_count = 0
                
                for item in limit_data:
                    ts_code = item.get("ts_code", "")
                    
                    # 检查是否在数据库中
                    if ts_code not in valid_stocks:
                        filtered_count += 1
                        continue
                    
                    # 检查是否为 ST 股票
                    stock_name = valid_stocks[ts_code].get("name", "")
                    if self._is_st_stock(stock_name):
                        st_count += 1
                        continue
                    
                    self._limit_stocks[ts_code] = item
                
                self._last_limit_fetch_date = today
                self.logger.info(
                    f"Loaded {len(self._limit_stocks)} limit prices "
                    f"(source={limit_source or '-'}, original={original_count}, "
                    f"filtered_not_in_db={filtered_count}, st={st_count})"
                )
            else:
                self.logger.warning("No limit price data returned")
                
        except Exception as e:
            self.logger.error(f"Failed to fetch limit prices: {e}")
    
    async def _get_all_watch_codes(self) -> List[str]:
        """
        获取所有需要监听的股票代码
        
        合并所有活跃策略的 watch_list。
        空 watch_list 表示不监听任何股票。
        必须明确包含 'ALL' 才会进行全市场监听。
        """
        watch_set = set()
        has_all_market = False
        
        for sub in self._subscriptions:
            if not sub.is_active:
                continue
            
            if sub.is_all_market():
                has_all_market = True
                # 继续遍历，收集其他策略的个股

            effective_watch_codes = await self._get_effective_watch_codes(sub)
            watch_set.update(effective_watch_codes)
        
        if has_all_market:
            # 全市场监听：使用涨跌停列表中的股票 + 其他策略的个股
            all_codes = set(self._limit_stocks.keys())
            all_codes.update(watch_set)
            return list(all_codes)
        
        return list(watch_set)

    async def _get_effective_watch_codes(self, subscription: StrategySubscription) -> List[str]:
        watch_set = {
            str(code).upper()
            for code in subscription.watch_list
            if str(code).strip() and str(code).upper() != "ALL"
        }

        position_codes = await self._get_position_watch_codes(subscription)
        watch_set.update(position_codes)

        transition_source_codes = await self._get_transition_source_watch_codes(subscription)
        watch_set.update(transition_source_codes)

        return list(watch_set)

    async def _get_position_watch_codes(self, subscription: StrategySubscription) -> List[str]:
        group_id = str(subscription.params.get("position_group_id") or "").strip()
        if not group_id:
            return []

        docs = await mongo_manager.find_many(
            "trade_review_positions",
            {
                "group_id": group_id,
                "quantity": {"$gt": 0},
                "$or": [
                    {"security_type": {"$exists": False}},
                    {"security_type": "stock"},
                ],
            },
            projection={"ts_code": 1},
        )
        return [
            str(doc.get("ts_code")).upper()
            for doc in docs
            if doc.get("ts_code")
        ]

    async def _get_transition_source_watch_codes(self, subscription: StrategySubscription) -> List[str]:
        rules = subscription.params.get("transition_rules") or []
        if not isinstance(rules, list) or not rules:
            return []

        source_pool_ids: set[str] = set()
        for rule in rules:
            if not isinstance(rule, dict) or not rule.get("enabled", True):
                continue
            for pool_id in rule.get("source_pool_ids") or []:
                normalized = str(pool_id or "").strip()
                if normalized:
                    source_pool_ids.add(normalized)

        if not source_pool_ids:
            return []

        source_pools = await mongo_manager.find_many(
            "stock_pools",
            {"pool_id": {"$in": list(source_pool_ids)}},
            projection={"stocks.ts_code": 1},
        )

        codes: set[str] = set()
        for pool in source_pools:
            for item in pool.get("stocks", []) or []:
                ts_code = str(item.get("ts_code") or "").strip().upper()
                if ts_code:
                    codes.add(ts_code)
        return list(codes)
    
    def _build_snapshot(
        self,
        quotes: Dict[str, Dict[str, Any]] | List[Dict[str, Any]],
    ) -> MarketSnapshot:
        """
        构建市场快照
        
        Args:
            quotes: 实时行情列表
            
        Returns:
            市场快照对象
        """
        snapshot = MarketSnapshot()
        
        quote_items: Iterable[Dict[str, Any]]
        if isinstance(quotes, dict):
            quote_items = quotes.values()
        else:
            quote_items = quotes
        
        quote_list = list(quote_items)
        
        # 调试日志：查看输入数据
        self.logger.info(f"[build_snapshot] Input quotes count: {len(quote_list)}")
        if quote_list:
            sample = quote_list[0]
            self.logger.info(f"[build_snapshot] Sample quote keys: {list(sample.keys())[:10]}")
        
        up_count = 0
        down_count = 0
        no_ts_code_count = 0
        
        for quote in quote_list:
            # ts_code 可能是大写或小写
            ts_code = quote.get("ts_code") or quote.get("TS_CODE", "")
            if not ts_code:
                no_ts_code_count += 1
                continue
            
            # 统一转换为大写
            ts_code = ts_code.upper()
            
            # 确保字段名小写
            normalized_quote = {k.lower(): v for k, v in quote.items()}
            normalized_quote["ts_code"] = ts_code
            
            snapshot.quotes[ts_code] = normalized_quote
            
            pct_chg = normalized_quote.get("pct_chg", 0) or 0
            if pct_chg > 0:
                up_count += 1
            elif pct_chg < 0:
                down_count += 1
        
        if no_ts_code_count > 0:
            self.logger.warning(f"[build_snapshot] Skipped {no_ts_code_count} quotes without ts_code")
        
        self.logger.info(f"[build_snapshot] Built snapshot with {len(snapshot.quotes)} stocks")
        
        snapshot.total_stocks = len(snapshot.quotes)
        snapshot.up_count = up_count
        snapshot.down_count = down_count
        
        # 添加涨跌停信息
        snapshot.limit_stocks = self._limit_stocks.copy()
        snapshot.limit_up_count = sum(
            1 for item in self._limit_stocks.values()
            if item.get("limit_type") == "U"
        )
        snapshot.limit_down_count = sum(
            1 for item in self._limit_stocks.values()
            if item.get("limit_type") == "D"
        )
        
        return snapshot
    
    async def _evaluate_strategies(self) -> List[StrategyAlert]:
        """
        执行所有策略评估
        
        Returns:
            触发的预警列表
        """
        if not self._current_snapshot:
            return []
        
        all_alerts = []
        
        for subscription in self._subscriptions:
            if not subscription.is_active:
                continue
            
            # 获取策略执行器
            strategy = self._strategies.get(subscription.strategy_type.value)
            if not strategy:
                self.logger.warning(
                    f"Unknown strategy type: {subscription.strategy_type}, "
                    f"subscription_id={subscription.subscription_id}"
                )
                continue
            
            try:
                effective_watch_codes = await self._get_effective_watch_codes(subscription)
                effective_subscription = subscription.copy(
                    update={
                        "watch_list": (
                            ["ALL", *effective_watch_codes]
                            if subscription.is_all_market()
                            else effective_watch_codes
                        )
                    }
                )
                alerts = await strategy.evaluate(
                    subscription=effective_subscription,
                    snapshot=self._current_snapshot,
                    previous_snapshot=self._previous_snapshot,
                )
                # 策略评估过程中可能会更新运行时参数（如 last_triggered_date、
                # highest_price 等）。评估时使用的是复制后的订阅对象，这里
                # 需要把 params 同步回原始订阅，避免下一轮轮询仍读取旧状态。
                subscription.params = effective_subscription.params
                all_alerts.extend(alerts)
                
            except Exception as e:
                self.logger.error(
                    f"Strategy evaluation error: {e}, "
                    f"strategy={subscription.strategy_type}"
                )
        
        return all_alerts

    async def _process_alert(self, alert: StrategyAlert) -> None:
        subscription = next(
            (sub for sub in self._subscriptions if sub.subscription_id == alert.subscription_id),
            None,
        )
        if not subscription:
            self.logger.warning(
                f"[poll] Unable to find subscription for alert {alert.alert_id} ({alert.subscription_id})"
            )
            return

        event_id = uuid.uuid4().hex
        event_doc = {
            "event_id": event_id,
            "alert_id": alert.alert_id,
            "trace_id": alert.trace_id,
            "subscription_id": alert.subscription_id,
            "strategy_id": alert.strategy_id,
            "strategy_name": alert.strategy_name,
            "strategy_type": subscription.strategy_type.value,
            "ts_code": alert.ts_code,
            "stock_name": alert.stock_name,
            "trigger_price": alert.trigger_price,
            "trigger_reason": alert.trigger_reason,
            "extra_data": alert.extra_data,
            "triggered_at": alert.triggered_at,
            "notification_channel_id": str(subscription.params.get("notification_channel_id") or ""),
            "notification_user_id": subscription.user_id,
            "notification_sent": False,
            "transition_results": [],
        }
        await mongo_manager.insert_one("listener_trigger_events", event_doc)

        notification_sent = await notification_manager.send_alert(
            alert,
            user_id=subscription.user_id,
            channel_id=str(subscription.params.get("notification_channel_id") or "") or None,
        )
        transition_results = await self._execute_transition_rules(
            subscription=subscription,
            alert=alert,
            event_id=event_id,
        )

        await mongo_manager.update_one(
            "listener_trigger_events",
            {"event_id": event_id},
            {
                "$set": {
                    "notification_sent": notification_sent,
                    "transition_results": transition_results,
                    "updated_at": datetime.utcnow(),
                }
            },
        )
        self.logger.info(
            f"[poll] Alert processed: notification_sent={notification_sent}, "
            f"transitions={len(transition_results)}"
        )

    async def _execute_transition_rules(
        self,
        subscription: StrategySubscription,
        alert: StrategyAlert,
        event_id: str,
    ) -> List[Dict[str, Any]]:
        rules = subscription.params.get("transition_rules") or []
        if not isinstance(rules, list) or not rules:
            return []

        results: List[Dict[str, Any]] = []
        for raw_rule in rules:
            if not isinstance(raw_rule, dict):
                continue
            result = await self._apply_transition_rule(
                subscription=subscription,
                alert=alert,
                event_id=event_id,
                rule=raw_rule,
            )
            if result:
                results.append(result)
        return results

    async def _apply_transition_rule(
        self,
        subscription: StrategySubscription,
        alert: StrategyAlert,
        event_id: str,
        rule: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        rule_id = str(rule.get("rule_id") or uuid.uuid4().hex)
        if not rule.get("enabled", True):
            return None

        target_pool_id = str(rule.get("target_pool_id", "")).strip()
        if not target_pool_id:
            return {
                "rule_id": rule_id,
                "status": "failed",
                "reason": "未配置目标股池",
            }

        cooldown_days = max(1, int(rule.get("cooldown_days", 1) or 1))
        if await self._is_transition_in_cooldown(rule_id, alert.ts_code, cooldown_days):
            result = {
                "rule_id": rule_id,
                "status": "skipped",
                "reason": f"{cooldown_days} 天冷却期内已流转",
                "target_pool_id": target_pool_id,
            }
            await self._write_transition_log(
                alert=alert,
                subscription=subscription,
                event_id=event_id,
                rule=rule,
                status=result["status"],
                reason=result["reason"],
                from_pool_ids=[],
                to_pool_id=target_pool_id,
            )
            return result

        target_pool = await mongo_manager.find_one("stock_pools", {"pool_id": target_pool_id})
        if not target_pool:
            result = {
                "rule_id": rule_id,
                "status": "failed",
                "reason": "目标股池不存在",
                "target_pool_id": target_pool_id,
            }
            await self._write_transition_log(
                alert=alert,
                subscription=subscription,
                event_id=event_id,
                rule=rule,
                status=result["status"],
                reason=result["reason"],
                from_pool_ids=[],
                to_pool_id=target_pool_id,
            )
            return result

        stock_basic = await mongo_manager.find_one(
            "stock_basic",
            {"ts_code": alert.ts_code},
            projection={"ts_code": 1, "symbol": 1, "name": 1},
        )
        stock_name = (stock_basic or {}).get("name") or alert.stock_name or alert.ts_code
        stock_code = (stock_basic or {}).get("symbol") or alert.ts_code.split(".")[0]

        now = datetime.utcnow()
        transition_date = date.today().strftime("%Y%m%d")
        mode = str(rule.get("mode", "move") or "move").strip().lower()
        source_pool_ids = [
            str(pool_id).strip()
            for pool_id in (rule.get("source_pool_ids") or [])
            if str(pool_id).strip() and str(pool_id).strip() != target_pool_id
        ]

        removed_from: List[str] = []
        removed_from_names: List[str] = []
        if mode == "move" and source_pool_ids:
            source_pools = await mongo_manager.find_many(
                "stock_pools",
                {"pool_id": {"$in": source_pool_ids}},
            )
            for pool in source_pools:
                stocks = pool.get("stocks", [])
                filtered_stocks = [
                    item for item in stocks
                    if str(item.get("ts_code", "")).upper() != alert.ts_code.upper()
                ]
                if len(filtered_stocks) == len(stocks):
                    continue
                removed_from.append(str(pool.get("pool_id")))
                removed_from_names.append(str(pool.get("name") or pool.get("pool_id") or ""))
                await mongo_manager.update_one(
                    "stock_pools",
                    {"pool_id": pool.get("pool_id")},
                    {
                        "$set": {
                            "stocks": filtered_stocks,
                            "updated_at": now,
                        }
                    },
                )

        target_stocks = list(target_pool.get("stocks", []))
        existing_index = next(
            (
                index for index, item in enumerate(target_stocks)
                if str(item.get("ts_code", "")).upper() == alert.ts_code.upper()
            ),
            None,
        )
        stock_payload = {
            "ts_code": alert.ts_code,
            "code": stock_code,
            "name": stock_name,
            "status": "active",
            "source_module": "listener_transition",
            "source_query": alert.trigger_reason,
            "source_pool_name": "、".join([name for name in removed_from_names if name]) or None,
            "source_type": "listener_alert",
            "source_strategy": subscription.strategy_type.value,
            "source_event_id": event_id,
            "operator_type": "auto",
            "transition_rule_id": rule_id,
            "last_transition_at": now,
            "entered_at": now,
            "added_at": now,
        }

        target_changed = False
        if existing_index is None:
            target_stocks.append(stock_payload)
            target_changed = True
        else:
            existing_item = dict(target_stocks[existing_index])
            stock_payload["entered_at"] = existing_item.get("entered_at") or existing_item.get("added_at") or now
            stock_payload["added_at"] = existing_item.get("added_at") or existing_item.get("entered_at") or now
            target_stocks[existing_index] = {**existing_item, **stock_payload}
            target_changed = True

        if target_changed:
            await mongo_manager.update_one(
                "stock_pools",
                {"pool_id": target_pool_id},
                {
                    "$set": {
                        "stocks": target_stocks,
                        "updated_at": now,
                    }
                },
            )

        status = "moved" if removed_from else ("copied" if existing_index is None else "updated")
        reason = (
            f"已自动流转到 {target_pool.get('name', target_pool_id)}"
            + (f"，并从 {len(removed_from)} 个来源池移出" if removed_from else "")
        )

        await self._write_transition_log(
            alert=alert,
            subscription=subscription,
            event_id=event_id,
            rule=rule,
            status=status,
            reason=reason,
            from_pool_ids=removed_from,
            from_pool_names=removed_from_names,
            to_pool_id=target_pool_id,
        )

        return {
            "rule_id": rule_id,
            "status": status,
            "reason": reason,
            "target_pool_id": target_pool_id,
            "target_pool_name": target_pool.get("name"),
            "from_pool_ids": removed_from,
            "transition_date": transition_date,
        }

    async def _is_transition_in_cooldown(
        self,
        rule_id: str,
        ts_code: str,
        cooldown_days: int,
    ) -> bool:
        records = await mongo_manager.find_many(
            "pool_transition_logs",
            {
                "rule_id": rule_id,
                "ts_code": ts_code,
                "status": {"$in": ["moved", "copied", "updated"]},
            },
            sort=[("created_at", -1)],
            limit=1,
        )
        if not records:
            return False

        last_time = records[0].get("created_at")
        if not isinstance(last_time, datetime):
            return False
        return (datetime.utcnow().date() - last_time.date()).days < cooldown_days

    async def _write_transition_log(
        self,
        alert: StrategyAlert,
        subscription: StrategySubscription,
        event_id: str,
        rule: Dict[str, Any],
        status: str,
        reason: str,
        from_pool_ids: List[str],
        from_pool_names: List[str],
        to_pool_id: str,
    ) -> None:
        await mongo_manager.insert_one(
            "pool_transition_logs",
            {
                "transition_id": uuid.uuid4().hex,
                "event_id": event_id,
                "rule_id": str(rule.get("rule_id") or ""),
                "subscription_id": subscription.subscription_id,
                "strategy_id": subscription.strategy_id,
                "strategy_type": subscription.strategy_type.value,
                "ts_code": alert.ts_code,
                "stock_name": alert.stock_name,
                "action_type": str(rule.get("mode", "move") or "move"),
                "from_pool_ids": from_pool_ids,
                "from_pool_names": [str(name) for name in from_pool_names if str(name).strip()],
                "to_pool_id": to_pool_id,
                "operator_type": "auto",
                "status": status,
                "reason": reason,
                "transition_date": date.today().strftime("%Y%m%d"),
                "trigger_reason": alert.trigger_reason,
                "trigger_price": alert.trigger_price,
                "cooldown_days": max(1, int(rule.get("cooldown_days", 1) or 1)),
            },
        )
    
    # ==================== 实时市场数据 ====================
    
    async def _store_realtime_market_data(self, index_quotes: Dict[str, Dict[str, Any]]) -> None:
        """
        存储实时市场数据到 Redis
        
        包括：三大指数 + 涨跌统计
        """
        if not self._current_snapshot:
            return
        
        # 解析指数数据
        sh_data = index_quotes.get("000001.SH", {})
        sz_data = index_quotes.get("399001.SZ", {})
        cyb_data = index_quotes.get("399006.SZ", {})
        
        # 统计涨跌停家数（从涨跌停列表统计）
        limit_up_count = 0
        limit_down_count = 0
        
        for quote in self._current_snapshot.quotes.values():
            ts_code = quote.get("ts_code", "")
            limit_info = self._limit_stocks.get(ts_code, {})
            
            # 判断涨停：当前价 >= 涨停价
            current_price = quote.get("price") or quote.get("close", 0)
            up_limit = limit_info.get("up_limit", 0)
            down_limit = limit_info.get("down_limit", 0)
            
            if up_limit and current_price and current_price >= up_limit:
                limit_up_count += 1
            elif down_limit and current_price and current_price <= down_limit:
                limit_down_count += 1
        
        # 构建数据
        market_data = {
            # 三大指数
            "sh_index": sh_data.get("close") or sh_data.get("price", 0),
            "sh_change": sh_data.get("pct_chg") or sh_data.get("pct_change", 0),
            "sz_index": sz_data.get("close") or sz_data.get("price", 0),
            "sz_change": sz_data.get("pct_chg") or sz_data.get("pct_change", 0),
            "cyb_index": cyb_data.get("close") or cyb_data.get("price", 0),
            "cyb_change": cyb_data.get("pct_chg") or cyb_data.get("pct_change", 0),
            # 涨跌统计
            "up_count": self._current_snapshot.up_count,
            "down_count": self._current_snapshot.down_count,
            "flat_count": self._current_snapshot.total_stocks - self._current_snapshot.up_count - self._current_snapshot.down_count,
            "limit_up": limit_up_count,
            "limit_down": limit_down_count,
            # 更新时间
            "update_time": market_now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        
        # 存入 Redis
        try:
            await redis_manager.set_realtime_market_data(market_data)
            self.logger.debug(
                f"[poll] Stored realtime market data: "
                f"SH={market_data['sh_index']:.2f}({market_data['sh_change']:+.2f}%), "
                f"up={market_data['up_count']}, down={market_data['down_count']}, "
                f"limit_up={limit_up_count}, limit_down={limit_down_count}"
            )
        except Exception as e:
            self.logger.error(f"Failed to store realtime market data: {e}")
    
    # ==================== 工具方法 ====================
    
    async def _get_valid_stocks_from_db(self) -> Dict[str, Dict[str, Any]]:
        """
        从数据库获取有效股票列表
        
        Returns:
            {ts_code: {name, industry, ...}}
        """
        try:
            stocks = await mongo_manager.find_many(
                "stock_basic",
                {"list_status": "L"},  # 只获取上市状态的股票
                projection={"ts_code": 1, "name": 1, "industry": 1, "_id": 0}
            )
            return {
                stock["ts_code"]: stock
                for stock in stocks
                if stock.get("ts_code")
            }
        except Exception as e:
            self.logger.error(f"Failed to get valid stocks from db: {e}")
            return {}
    
    def _is_st_stock(self, stock_name: str) -> bool:
        """
        判断是否为 ST 股票
        
        根据股票名称判断，包含 ST、*ST、S*ST 等
        """
        if not stock_name:
            return False
        
        name_upper = stock_name.upper()
        st_patterns = ["ST", "*ST", "S*ST", "SST"]
        
        for pattern in st_patterns:
            if name_upper.startswith(pattern):
                return True
        
        return False
    
    async def _is_trading_time(self) -> bool:
        """检查是否为交易时间"""
        return await data_source_manager.is_trading_time()
    
    def _parse_time(self, time_str: str) -> time:
        """
        解析时间字符串
        
        Args:
            time_str: 时间字符串 (格式: HH:MM)
            
        Returns:
            time 对象
        """
        parts = time_str.split(":")
        return time(int(parts[0]), int(parts[1]))
    
    # ==================== 健康检查 ====================
    
    async def health_check(self) -> dict:
        """健康检查"""
        base_health = await super().health_check()
        
        base_health.update({
            "subscriptions": len(self._subscriptions),
            "strategies": list(self._strategies.keys()),
            "limit_stocks_loaded": len(self._limit_stocks),
            "last_limit_fetch_date": self._last_limit_fetch_date,
            "has_current_snapshot": self._current_snapshot is not None,
        })
        
        return base_health
