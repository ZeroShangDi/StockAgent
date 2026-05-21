"""
通知管理器 (企业微信 Webhook)

负责:
- 发送企业微信 Markdown 消息
- 发送企业微信 / 钉钉 文本消息
- 消息频率控制
- 失败重试
"""

import asyncio
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
import httpx

from core.base import BaseManager
from ..settings import settings
from ..protocols import StrategyAlert
from .mongo_manager import mongo_manager


class NotificationManager(BaseManager):
    """
    通知管理器
    
    支持发送 Markdown 格式的企业微信 Webhook 消息。
    内置消息频率控制，防止刷屏。
    
    Example:
        await notification_manager.send_alert(alert)
        await notification_manager.send_markdown("### 标题\n内容")
    """
    
    def __init__(self):
        super().__init__()
        self._config = settings.notification
        self._client: Optional[httpx.AsyncClient] = None
        self._last_send_time: Dict[str, datetime] = {}  # 按策略ID记录最后发送时间
        self._send_queue: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()

    def _prune_last_send_time(self) -> None:
        """清理长期未使用的频控状态，避免常驻进程无限增长。"""
        if not self._last_send_time:
            return
        keep_seconds = max(int(self._config.min_interval) * 6, 24 * 3600)
        cutoff = datetime.utcnow().timestamp() - keep_seconds
        stale_keys = [
            strategy_id
            for strategy_id, last_time in self._last_send_time.items()
            if last_time.timestamp() < cutoff
        ]
        for strategy_id in stale_keys:
            self._last_send_time.pop(strategy_id, None)
    
    async def initialize(self) -> None:
        """初始化 HTTP 客户端"""
        if self._initialized:
            return

        self.logger.info("Initializing NotificationManager...")

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=20),
            headers={"Content-Type": "application/json"},
        )

        if not self._config.is_configured:
            self.logger.warning("Default notification webhook not configured, user-bound channels may still be used")

        self._initialized = True
        self.logger.info("NotificationManager initialized ✓")
    
    async def shutdown(self) -> None:
        """关闭 HTTP 客户端"""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._last_send_time.clear()
        self._initialized = False
        self.logger.info("NotificationManager shutdown")
    
    async def health_check(self) -> bool:
        """健康检查"""
        return self._initialized
    
    async def _resolve_user_channel(
        self,
        user_id: Optional[str],
        channel_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        if not user_id or not channel_id:
            return None

        user = await mongo_manager.find_one(
            "users",
            {"user_id": user_id},
            projection={"notification_channels": 1, "preferences.notification_enabled": 1},
        )
        if not user:
            return None

        preferences = user.get("preferences", {}) or {}
        if preferences.get("notification_enabled") is False:
            return None

        channels = user.get("notification_channels", []) or []
        for channel in channels:
            if not isinstance(channel, dict):
                continue
            if str(channel.get("channel_id") or "") == channel_id:
                return channel
        return None

    async def _resolve_delivery_target(
        self,
        user_id: Optional[str],
        channel_id: Optional[str],
    ) -> Optional[Tuple[str, str, str]]:
        if user_id:
            user = await mongo_manager.find_one(
                "users",
                {"user_id": user_id},
                projection={"preferences.notification_enabled": 1},
            )
            preferences = user.get("preferences", {}) if user else {}
            if preferences.get("notification_enabled") is False:
                return None

        custom_channel = await self._resolve_user_channel(user_id=user_id, channel_id=channel_id)
        if custom_channel:
            provider = str(custom_channel.get("provider") or "").strip().lower()
            webhook = str(custom_channel.get("webhook") or "").strip()
            keyword = str(custom_channel.get("keyword") or "").strip()
            if provider and webhook:
                return provider, webhook, keyword

        if self._config.is_configured and self._config.wecom_webhook:
            return "wecom", self._config.wecom_webhook, ""

        return None

    async def send_alert(
        self,
        alert: StrategyAlert,
        user_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> bool:
        """
        发送策略预警消息
        
        Args:
            alert: 预警对象
            user_id: 所属用户
            channel_id: 用户绑定的通知机器人 ID
            dry_run: 仅构建并记录消息，不实际发送
            
        Returns:
            是否发送成功
        """
        self.logger.info(
            f"[NOTIFY] send_alert called: ts_code={alert.ts_code}, "
            f"strategy={alert.strategy_name}, reason={alert.trigger_reason[:30]}..."
        )
        
        text_content = self.preview_alert(alert)
        if dry_run:
            self.logger.info(
                f"[NOTIFY] Dry-run alert preview generated successfully, length={len(text_content)}"
            )
            return True
        
        if not self._config.enabled:
            self.logger.warning("[NOTIFY] Notification disabled (config.enabled=False)")
            return False
            
        delivery_target = await self._resolve_delivery_target(user_id=user_id, channel_id=channel_id)
        if not delivery_target:
            self.logger.warning(
                "[NOTIFY] Notification not configured (no user channel and no default webhook)"
            )
            return False
        
        # 频率控制
        async with self._lock:
            self._prune_last_send_time()
            last_time = self._last_send_time.get(alert.strategy_id)
            if last_time:
                elapsed = (datetime.utcnow() - last_time).total_seconds()
                if elapsed < self._config.min_interval:
                    self.logger.warning(
                        f"[NOTIFY] Rate limited: strategy={alert.strategy_id}, "
                        f"elapsed={elapsed:.1f}s < min_interval={self._config.min_interval}s"
                    )
                    return False
        
        # 构建消息（使用纯文本格式，兼容性更好）
        self.logger.info(f"[NOTIFY] Sending text message, length={len(text_content)}")
        
        provider, webhook, keyword = delivery_target
        success = await self._send_text_via_target(
            provider=provider,
            webhook=webhook,
            content=text_content,
            keyword=keyword,
        )
        
        if success:
            async with self._lock:
                self._last_send_time[alert.strategy_id] = datetime.utcnow()
            self.logger.info(f"[NOTIFY] ★ Alert sent successfully: {alert.ts_code}")
        else:
            self.logger.error(f"[NOTIFY] Failed to send alert: {alert.ts_code}")
        
        return success

    def preview_alert(self, alert: StrategyAlert) -> str:
        """生成策略预警的文本预览，用于本地验证或 dry-run。"""
        return self._build_alert_text(alert)
    
    async def send_markdown(
        self, 
        content: str, 
        mentioned_list: Optional[List[str]] = None,
        mentioned_mobile_list: Optional[List[str]] = None,
    ) -> bool:
        """
        发送 Markdown 消息
        
        Args:
            content: Markdown 内容
            mentioned_list: 需要 @ 的用户ID列表，使用 "@all" 表示 @ 所有人
            mentioned_mobile_list: 需要 @ 的用户手机号列表
            
        Returns:
            是否发送成功
        """
        if not self._config.is_configured:
            self.logger.warning("Webhook not configured, cannot send message")
            return False
        
        self._ensure_initialized()
        
        # 如果有 @ 需求，在内容末尾添加提醒
        final_content = content
        if mentioned_list and "@all" in mentioned_list:
            final_content = content + "\n<@all>"
        
        # 企业微信 Markdown 消息限制约 4096 字符
        MAX_LENGTH = 4000
        if len(final_content) > MAX_LENGTH:
            self.logger.warning(f"Message too long ({len(final_content)} chars), truncating...")
            # 截断并添加提示
            final_content = final_content[:MAX_LENGTH - 50] + "\n\n... 内容过长已截断"
        
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": final_content
            }
        }
        
        try:
            response = await self._client.post(
                self._config.wecom_webhook,
                json=payload,
            )
            response.raise_for_status()
            
            result = response.json()
            if result.get("errcode") == 0:
                self.logger.info(f"Notification sent successfully: {content[:50]}...")
                return True
            else:
                self.logger.error(f"Notification failed: {result}")
                return False
                
        except httpx.HTTPError as e:
            self.logger.error(f"HTTP error sending notification: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Error sending notification: {e}")
            return False
    
    async def send_text(self, content: str, mentioned_list: Optional[List[str]] = None) -> bool:
        """
        发送文本消息
        
        Args:
            content: 文本内容
            mentioned_list: 需要 @ 的用户ID列表，使用 "@all" 表示 @ 所有人
            
        Returns:
            是否发送成功
        """
        if not self._config.is_configured:
            self.logger.warning("Webhook not configured, cannot send message")
            return False
        
        self._ensure_initialized()
        return await self._send_text_via_target(
            provider="wecom",
            webhook=self._config.wecom_webhook,
            content=content,
            mentioned_list=mentioned_list,
        )

    async def _send_text_via_target(
        self,
        provider: str,
        webhook: str,
        content: str,
        keyword: str = "",
        mentioned_list: Optional[List[str]] = None,
    ) -> bool:
        self._ensure_initialized()

        payload: Dict[str, Any]
        provider_key = provider.strip().lower()
        final_content = self._prepare_text_content(
            provider=provider_key,
            content=content,
            keyword=keyword,
        )
        if provider_key == "dingtalk":
            payload = {
                "msgtype": "text",
                "text": {"content": final_content},
            }
        else:
            payload = {
                "msgtype": "text",
                "text": {"content": final_content},
            }

        if provider_key == "wecom" and mentioned_list:
            payload["text"]["mentioned_list"] = mentioned_list

        try:
            response = await self._client.post(webhook, json=payload)
            response.raise_for_status()
            result = response.json()
            success = result.get("errcode") == 0
            if not success:
                self.logger.error(
                    "Notification provider returned failure: provider=%s, keyword=%s, result=%s",
                    provider_key,
                    keyword or "-",
                    result,
                )
            return success
        except Exception as e:
            self.logger.error(f"Error sending {provider_key} text notification: {e}")
            return False

    def _prepare_text_content(
        self,
        provider: str,
        content: str,
        keyword: str = "",
    ) -> str:
        """为不同通知渠道补充必要的消息前缀。"""
        if provider == "dingtalk":
            normalized_keyword = keyword.strip()
            if normalized_keyword and normalized_keyword not in content:
                return f"{normalized_keyword}\n{content}"
        return content
    
    def _build_alert_text(self, alert: StrategyAlert) -> str:
        """
        构建预警消息的纯文本内容 (企业微信兼容格式)
        
        Args:
            alert: 预警对象
            
        Returns:
            纯文本格式的消息内容
        """
        # 根据触发类型选择图标
        limit_type = alert.extra_data.get("limit_type", "")
        if limit_type == "up":
            icon = "🔔"
            title = "涨停打开提醒"
        elif limit_type == "down":
            icon = "🔔"
            title = "跌停打开提醒"
        else:
            icon = "🔔"
            title = alert.strategy_name
        
        # 时间
        time_str = alert.triggered_at.strftime('%H:%M:%S')
        
        # 获取涨跌停价格
        limit_price = alert.extra_data.get("up_limit") or alert.extra_data.get("down_limit", 0)
        limit_price_str = f"{limit_price:.2f}" if limit_price else "-"
        
        # 纯文本格式
        content = (
            f"{icon} {title}\n"
            f"股票: {alert.stock_name} ({alert.ts_code})\n"
            f"策略: {alert.strategy_name}\n"
            f"涨跌停价格: {limit_price_str}\n"
            f"当前价格: {alert.trigger_price:.2f}\n"
            f"触发原因: {alert.trigger_reason}\n"
            f"时间: {time_str}"
        )
        
        return content
    
    def _build_alert_markdown(self, alert: StrategyAlert) -> str:
        """
        构建预警消息的 Markdown 内容 (备用)
        
        Args:
            alert: 预警对象
            
        Returns:
            Markdown 格式的消息内容
        """
        time_str = alert.triggered_at.strftime('%H:%M:%S')
        
        content = f"""📢 **{alert.strategy_name}**
> **{alert.stock_name}** ({alert.ts_code})
> 当前价: ¥{alert.trigger_price:.2f}
> {alert.trigger_reason}
> 时间: {time_str}"""
        
        return content


# 全局单例
notification_manager = NotificationManager()
