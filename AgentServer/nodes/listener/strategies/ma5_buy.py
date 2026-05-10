"""
均线低吸策略

策略逻辑:
1. 股价从上方回落到指定均线附近
2. 在均线上方企稳（连续 N 个轮询周期站稳）

盘中均线估算方式:
- MA(N) = (前 N-1 天收盘价 + 盘中估算收盘价) / N
- 盘中估算收盘价沿用当前项目原有的开盘价 5% 上浮近似
- 支持全局默认均线周期，也支持单股覆盖

企稳判断 (状态机):
- 状态0: 初始/正常状态
- 状态1: 首次发现回落到均线附近 (从上方回落)
- 状态2: 连续 N 个周期在均线上方 → 触发通知
"""

from typing import List, Dict, Any, Optional
from datetime import date, datetime
from enum import IntEnum
import logging

from .base import BaseStrategy
from core.protocols import (
    StrategySubscription,
    StrategyAlert,
    MarketSnapshot,
)
from common.enums import StrategyType
from core.managers import mongo_manager


class StockState(IntEnum):
    """股票状态"""
    NORMAL = 0      # 正常状态
    TOUCHED = 1     # 已触及5日线
    STABILIZED = 2  # 企稳确认


class StockTracker:
    """单只股票的状态追踪"""
    
    def __init__(self):
        self.state: StockState = StockState.NORMAL
        self.touch_time: Optional[datetime] = None  # 首次触及时间
        self.stable_count: int = 0  # 在5日线上方的连续次数
        self.alerted_today: bool = False  # 今日是否已触发
    
    def reset(self):
        """重置状态"""
        self.state = StockState.NORMAL
        self.touch_time = None
        self.stable_count = 0


class MA5BuyStrategy(BaseStrategy):
    """
    均线低吸策略
    
    参数:
    - ma_period: 默认均线周期 (默认 5)
    - touch_range: 触及均线的范围 (默认 0.02，即 ±2%)
    - stable_periods: 企稳需要的连续周期数 (默认 2)
    - once_per_day: 每只股票每天只触发一次 (默认 True)

    单股覆盖参数:
    - stock_configs[ts_code].ma_period
    - stock_configs[ts_code].touch_range
    - stock_configs[ts_code].stable_periods
    - stock_configs[ts_code].enabled
    """
    
    def __init__(self):
        self.logger = logging.getLogger("strategy.ma5_buy")
        
        # 股票历史缓存 {ts_code: {records, latest_trade_date}}
        self._stock_data: Dict[str, Dict[str, Any]] = {}
        
        # 股票状态追踪 {ts_code: StockTracker}
        self._trackers: Dict[str, StockTracker] = {}
        
        # 缓存日期
        self._cache_date: Optional[str] = None
    
    @property
    def strategy_type(self) -> str:
        return StrategyType.MA5_BUY.value
    
    async def evaluate(
        self,
        subscription: StrategySubscription,
        snapshot: MarketSnapshot,
        previous_snapshot: Optional[MarketSnapshot] = None,
    ) -> List[StrategyAlert]:
        """评估均线低吸条件"""
        alerts = []
        
        default_touch_range = self._normalize_percent_value(
            self._get_numeric_param(subscription.params, "touch_range", 0.02)
        )
        default_stable_periods = int(
            self._get_numeric_param(subscription.params, "stable_periods", 2.0)
        )
        default_ma_period = max(2, int(self._get_numeric_param(subscription.params, "ma_period", 5.0)))
        today_key = date.today().strftime("%Y%m%d")
        
        # 确保缓存数据是今天的
        await self._ensure_cache_updated()
        
        # 全市场监听时自动过滤 ST 股票
        exclude_st = subscription.is_all_market()
        watch_stocks = self._get_watch_stocks(subscription, snapshot, exclude_st=exclude_st)
        
        for ts_code, quote in watch_stocks.items():
            try:
                alert = await self._evaluate_stock(
                    ts_code=ts_code,
                    quote=quote,
                    subscription=subscription,
                    default_touch_range=default_touch_range,
                    default_stable_periods=default_stable_periods,
                    default_ma_period=default_ma_period,
                    today_key=today_key,
                )
                if alert:
                    alerts.append(alert)
                    
            except Exception as e:
                self.logger.error(f"Error evaluating {ts_code}: {e}")
        
        return alerts
    
    async def _evaluate_stock(
        self,
        ts_code: str,
        quote: Dict[str, Any],
        subscription: StrategySubscription,
        default_touch_range: float,
        default_stable_periods: int,
        default_ma_period: int,
        today_key: str,
    ) -> Optional[StrategyAlert]:
        """评估单只股票"""
        
        # 确保有数据缓存
        if ts_code not in self._stock_data:
            await self._load_stock_data(ts_code)
        
        data = self._stock_data.get(ts_code)
        if not data:
            return None

        runtime_config = self._get_stock_runtime_config(subscription, ts_code)
        ma_period = max(2, int(runtime_config.get("ma_period", default_ma_period) or default_ma_period))
        touch_range = self._normalize_percent_value(
            self._get_numeric_param(runtime_config, "touch_range", default_touch_range * 100)
        )
        stable_periods = max(1, int(runtime_config.get("stable_periods", default_stable_periods) or default_stable_periods))

        ma_context = self._calculate_ma_context(data.get("records") or [], ma_period)
        if not ma_context:
            return None
        ma_value = ma_context["ma_value"]
        prev_close = ma_context["prev_close"]
        
        # 获取或创建追踪器
        if ts_code not in self._trackers:
            self._trackers[ts_code] = StockTracker()
        tracker = self._trackers[ts_code]
        
        if self._should_skip_by_alert_frequency(subscription, ts_code, today_key):
            return None
        
        # 当前价格
        current_price = quote.get("price", 0)
        if not current_price:
            return None
        
        stock_name = quote.get("name", ts_code)
        
        # 计算与均线的距离
        distance_pct = (current_price / ma_value) - 1
        is_near_ma = abs(distance_pct) <= touch_range
        is_above_ma = current_price >= ma_value
        was_above_ma = prev_close > ma_value  # 昨天在均线上方
        
        # 状态机逻辑
        if tracker.state == StockState.NORMAL:
            # 条件: 昨天在均线上方，今天回落到均线附近
            if was_above_ma and is_near_ma:
                tracker.state = StockState.TOUCHED
                tracker.touch_time = datetime.now()
                tracker.stable_count = 1 if is_above_ma else 0
                self.logger.info(
                    f"[{ts_code}] 触及{ma_period}日均线: price={current_price:.2f}, "
                    f"MA={ma_value:.2f}, distance={distance_pct*100:.1f}%"
                )
        
        elif tracker.state == StockState.TOUCHED:
            if is_above_ma:
                # 在均线上方，计数+1
                tracker.stable_count += 1
                self.logger.debug(
                    f"[{ts_code}] 企稳计数: {tracker.stable_count}/{stable_periods}"
                )
                
                # 达到企稳条件
                if tracker.stable_count >= stable_periods:
                    tracker.state = StockState.STABILIZED
                    tracker.alerted_today = self._get_alert_frequency(subscription.params) != self.ALERT_FREQUENCY_UNLIMITED
                    
                    self.logger.info(
                        f"[ALERT] {ts_code} {ma_period}日均线企稳! "
                        f"price={current_price:.2f}, MA={ma_value:.2f}"
                    )
                    
                    # 创建预警
                    alert = self._create_alert(
                        subscription=subscription,
                        ts_code=ts_code,
                        stock_name=stock_name,
                        price=current_price,
                        reason=f"回落{ma_period}日均线后企稳，连续{stable_periods}个周期站稳",
                        extra_data={
                            "ma_period": ma_period,
                            "ma_value": round(ma_value, 2),
                            "prev_close": round(prev_close, 2),
                            "distance_to_ma": round(distance_pct * 100, 2),
                            "stable_count": tracker.stable_count,
                            "touch_time": tracker.touch_time.strftime("%H:%M:%S") if tracker.touch_time else "",
                        },
                    )
                    await self._record_alert_trigger(
                        subscription=subscription,
                        ts_code=ts_code,
                        today_key=today_key,
                    )
                    return alert
            else:
                # 跌破均线，重置状态
                if current_price < ma_value * (1 - touch_range):
                    self.logger.debug(f"[{ts_code}] 跌破{ma_period}日均线，重置状态")
                    tracker.reset()
        
        elif tracker.state == StockState.STABILIZED:
            # 已触发，等待下一个交易日
            pass
        
        return None
    
    async def _ensure_cache_updated(self) -> None:
        """确保缓存数据是今天的"""
        today = date.today().strftime("%Y%m%d")
        
        if self._cache_date != today:
            self._stock_data.clear()
            # 重置所有追踪器
            for tracker in self._trackers.values():
                tracker.reset()
                tracker.alerted_today = False
            self._cache_date = today
            self.logger.info(f"Cache reset for new trading day: {today}")
    
    async def _load_stock_data(self, ts_code: str) -> None:
        """
        加载股票历史数据缓存
        """
        try:
            # 取足够长的日线序列，支持不同均线周期的单股配置
            records = await mongo_manager.find_many(
                "stock_daily",
                {"ts_code": ts_code},
                sort=[("trade_date", -1)],
                limit=250,
            )
            
            if not records or len(records) < 2:
                self.logger.debug(f"Insufficient data for {ts_code}, got {len(records) if records else 0} records")
                return
            
            records.sort(key=lambda x: x.get("trade_date", ""), reverse=True)
            self._stock_data[ts_code] = {
                "records": records,
                "latest_trade_date": records[0].get("trade_date", ""),
            }
            self.logger.debug(f"Loaded {ts_code}: cached {len(records)} daily records")
            
        except Exception as e:
            self.logger.error(f"Failed to load data for {ts_code}: {e}")

    def _calculate_ma_context(self, records: List[Dict[str, Any]], ma_period: int) -> Optional[Dict[str, float]]:
        if ma_period < 2 or not records:
            return None

        today_str = date.today().strftime("%Y%m%d")
        latest_trade_date = str(records[0].get("trade_date") or "")
        has_today_record = latest_trade_date == today_str

        if has_today_record:
            today_open = float(records[0].get("open", 0) or 0)
            prev_close = float(records[1].get("close", 0) or 0) if len(records) > 1 else 0.0
            prev_records = records[1:ma_period]
        else:
            today_open = float(records[0].get("close", 0) or 0)
            prev_close = float(records[0].get("close", 0) or 0)
            prev_records = records[0:ma_period - 1]

        if not today_open or prev_close <= 0 or len(prev_records) < max(ma_period - 1, 0):
            return None

        prev_closes = [float(record.get("close", 0) or 0) for record in prev_records]
        if any(value <= 0 for value in prev_closes):
            return None

        estimated_close = today_open * 1.05
        ma_value = (sum(prev_closes) + estimated_close) / ma_period
        return {
            "ma_value": ma_value,
            "prev_close": prev_close,
        }
    
    async def preload_watch_list(self, ts_codes: List[str]) -> None:
        """
        预加载监听列表的历史数据
        
        可在每日开盘前调用，减少盘中数据库查询
        """
        self.logger.info(f"Preloading data for {len(ts_codes)} stocks...")
        
        await self._ensure_cache_updated()
        
        for ts_code in ts_codes:
            await self._load_stock_data(ts_code)
        
        self.logger.info(f"Preloaded {len(self._stock_data)} stocks")
    
    def get_tracker_status(self, ts_code: str) -> Dict[str, Any]:
        """获取股票追踪状态（调试用）"""
        tracker = self._trackers.get(ts_code)
        if not tracker:
            return {"state": "not_tracked"}
        
        return {
            "state": tracker.state.name,
            "touch_time": tracker.touch_time.isoformat() if tracker.touch_time else None,
            "stable_count": tracker.stable_count,
            "alerted_today": tracker.alerted_today,
        }
