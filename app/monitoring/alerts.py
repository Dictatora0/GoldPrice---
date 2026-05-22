from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass

from config import settings
from app.database import get_db_session
from app.logging_config import get_logger
from app.models import CustomAlertRule, NotificationDeliveryLog
from app.monitoring.custom_alerts import (
    evaluate_custom_rule,
    should_trigger_with_cooldown,
    _safe_load_channels,
)

logger = get_logger(__name__)

try:
    import apprise
    APPRISE_AVAILABLE = True
except ImportError:
    class _AppriseStub:
        class Apprise:
            def add(self, *args, **kwargs):
                return None

            def notify(self, *args, **kwargs):
                return False

    apprise = _AppriseStub()
    APPRISE_AVAILABLE = False


@dataclass
class AlertRule:
    """Alert rule definition"""
    name: str
    level: str  # "critical" or "warning"
    condition: Callable[[], bool]
    message: str
    channels: List[str]


class AlertManager:
    """告警管理器"""

    def __init__(self):
        self.apprise = apprise.Apprise()
        self.channel_clients: Dict[str, object] = {}
        self.last_alert_time: Dict[str, datetime] = defaultdict(lambda: datetime.min)
        self.rules: List[AlertRule] = []

        # 配置通知渠道
        if settings.enable_notification:
            self._register_channel("system", "macos://")
            self.channel_clients["macos"] = self.channel_clients["system"]

        if settings.alert_webhook_url:
            self._register_channel("webhook", settings.alert_webhook_url)

        if settings.alert_slack_webhook:
            self._register_channel("slack", f'slack://{settings.alert_slack_webhook}')

        if settings.alert_email_url:
            self._register_channel("email", settings.alert_email_url)

        if settings.alert_wechat_url:
            self._register_channel("wechat", settings.alert_wechat_url)

        # Initialize alert rules
        self._init_rules()

    @staticmethod
    def _normalize_channel_name(channel: str) -> str:
        key = channel.strip().lower()
        if key == "macos":
            return "system"
        return key

    def _max_attempts_for_channel(self, channel: str) -> int:
        def _to_total_attempts(retries: int) -> int:
            # retries 表示“失败后重试次数”，总尝试次数 = 1 + retries
            return 1 + max(0, int(retries))

        if channel == "email":
            return _to_total_attempts(settings.alert_email_max_retries)
        if channel == "wechat":
            return _to_total_attempts(settings.alert_wechat_max_retries)
        if channel in {"webhook", "slack"}:
            return _to_total_attempts(settings.alert_webhook_max_retries)
        return 1

    @staticmethod
    def _truncate_text(value: str, max_len: int) -> str:
        if len(value) <= max_len:
            return value
        return value[: max_len - 3] + "..."

    def _log_delivery(
        self,
        *,
        rule_name: str,
        channel: str,
        level: str,
        title: str,
        message: str,
        status: str,
        attempt: int,
        max_attempts: int,
        error_message: Optional[str] = None,
    ) -> None:
        try:
            with get_db_session() as session:
                session.add(
                    NotificationDeliveryLog(
                        rule_name=rule_name,
                        channel=channel,
                        level=level.lower(),
                        title=self._truncate_text(title, 255),
                        message=message,
                        status=status,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        error_message=self._truncate_text(error_message, 2000) if error_message else None,
                    )
                )
        except Exception:
            logger.warning("Failed to persist notification delivery log", exc_info=True)

    def _send_to_channel_with_retry(
        self,
        *,
        rule_name: str,
        level: str,
        title: str,
        message: str,
        channel: str,
        client: object,
    ) -> bool:
        max_attempts = self._max_attempts_for_channel(channel)
        for attempt in range(1, max_attempts + 1):
            error_message: Optional[str] = None
            status = "failed"
            try:
                result = client.notify(title=title, body=message)
                if bool(result):
                    status = "success"
                    self._log_delivery(
                        rule_name=rule_name,
                        channel=channel,
                        level=level,
                        title=title,
                        message=message,
                        status=status,
                        attempt=attempt,
                        max_attempts=max_attempts,
                    )
                    return True
                error_message = "notify returned false"
            except Exception as exc:
                error_message = str(exc)
                logger.warning(
                    "Alert delivery failed on channel=%s attempt=%s/%s",
                    channel,
                    attempt,
                    max_attempts,
                    exc_info=True,
                )
            self._log_delivery(
                rule_name=rule_name,
                channel=channel,
                level=level,
                title=title,
                message=message,
                status=status,
                attempt=attempt,
                max_attempts=max_attempts,
                error_message=error_message,
            )
        return False

    def _register_channel(self, key: str, url: str):
        self.apprise.add(url)
        client = apprise.Apprise()
        client.add(url)
        self.channel_clients[self._normalize_channel_name(key)] = client

    def send_alert(
        self,
        rule_name: str,
        level: str,
        title: str,
        message: str,
        channels: Optional[List[str]] = None,
    ) -> bool:
        """发送告警"""
        # 检查冷却时间
        if not self._should_send_alert(rule_name):
            return False

        # 发送通知
        try:
            formatted_title = f"[{level.upper()}] {title}"
            delivered = False

            requested_channels: List[str] = []
            if channels:
                for channel in channels:
                    if not isinstance(channel, str) or not channel.strip():
                        continue
                    key = self._normalize_channel_name(channel)
                    if key not in requested_channels:
                        requested_channels.append(key)

            # 保持兼容：未显式传入 channels 时仍尝试全部已注册渠道
            if not requested_channels:
                requested_channels = list(dict.fromkeys(self.channel_clients.keys()))

            if not requested_channels:
                delivered = bool(self.apprise.notify(title=formatted_title, body=message))
                self._log_delivery(
                    rule_name=rule_name,
                    channel="default",
                    level=level,
                    title=formatted_title,
                    message=message,
                    status="success" if delivered else "failed",
                    attempt=1,
                    max_attempts=1,
                    error_message=None if delivered else "no available channel and apprise notify returned false",
                )
            else:
                unique_targets: List[tuple[str, object]] = []
                seen_clients = set()

                for channel in requested_channels:
                    client = self.channel_clients.get(channel)
                    if client is None:
                        reason = f"channel '{channel}' is not configured"
                        logger.warning(
                            "Alert channel not configured: %s (rule=%s title=%s)",
                            channel,
                            rule_name,
                            title,
                        )
                        self._log_delivery(
                            rule_name=rule_name,
                            channel=channel,
                            level=level,
                            title=formatted_title,
                            message=message,
                            status="failed",
                            attempt=1,
                            max_attempts=1,
                            error_message=reason,
                        )
                        continue
                    client_id = id(client)
                    if client_id in seen_clients:
                        continue
                    seen_clients.add(client_id)
                    unique_targets.append((channel, client))

                for channel, client in unique_targets:
                    delivered = self._send_to_channel_with_retry(
                        rule_name=rule_name,
                        level=level,
                        title=formatted_title,
                        message=message,
                        channel=channel,
                        client=client,
                    ) or delivered

            if not delivered:
                logger.warning("Alert delivery returned false for all channels: %s", title)
            self.last_alert_time[rule_name] = datetime.now()
            return delivered
        except Exception as e:
            if not APPRISE_AVAILABLE:
                logger.warning("Alert backend unavailable, dropping alert: %s", title)
                return False
            logger.warning("Failed to send alert: %s", e)
            return False

    def _should_send_alert(self, rule_name: str) -> bool:
        """检查是否应该发送告警(冷却时间)"""
        last_time = self.last_alert_time.get(rule_name, datetime.min)
        cooldown = timedelta(minutes=settings.alert_cooldown_minutes)
        return datetime.now() - last_time > cooldown

    def _init_rules(self):
        """Initialize alert rules"""
        from app.monitoring.metrics import metrics_collector
        from app.cache import cache_manager
        from app.models import PriceHistory
        import psutil

        # Rule 1: Collector failure (>50% failure rate)
        def check_collector_failure() -> bool:
            if not settings.prometheus_enabled:
                return False
            try:
                # Get metrics from registry
                success_samples = {}
                failure_samples = {}
                for metric in metrics_collector.registry.collect():
                    if metric.name == 'gold_collector_success_total':
                        success_samples = {s.labels['source']: s.value for s in metric.samples if s.name == 'gold_collector_success_total'}
                    if metric.name == 'gold_collector_failure_total':
                        failure_samples = {s.labels['source']: s.value for s in metric.samples if s.name == 'gold_collector_failure_total'}

                # Calculate failure rate for each source
                for source in failure_samples:
                    total = success_samples.get(source, 0) + failure_samples.get(source, 0)
                    if total > 0:
                        failure_rate = failure_samples.get(source, 0) / total
                        if failure_rate > 0.5:
                            return True
                return False
            except Exception:
                logger.warning("Collector failure alert rule check failed", exc_info=True)
                return False

        self.rules.append(AlertRule(
            name="collector_failure",
            level="critical",
            condition=check_collector_failure,
            message="数据采集失败率超过50%",
            channels=["macos", "webhook"]
        ))

        # Rule 2: Price spike (>5% change in 1 hour)
        def check_price_spike() -> bool:
            try:
                one_hour_ago = datetime.now() - timedelta(hours=1)
                with get_db_session(read_only=True) as session:
                    # Get current price
                    current = session.query(PriceHistory.price_cny_per_gram)\
                        .order_by(PriceHistory.timestamp.desc())\
                        .first()

                    # Get price from 1 hour ago
                    old = session.query(PriceHistory.price_cny_per_gram)\
                        .filter(PriceHistory.timestamp <= one_hour_ago)\
                        .order_by(PriceHistory.timestamp.desc())\
                        .first()

                if current and old and old[0] > 0:
                    change_pct = abs((current[0] - old[0]) / old[0])
                    return change_pct > 0.05
                return False
            except Exception:
                logger.warning("Price spike alert rule check failed", exc_info=True)
                return False

        self.rules.append(AlertRule(
            name="price_spike",
            level="warning",
            condition=check_price_spike,
            message="价格异常波动超过5%",
            channels=["macos"]
        ))

        # Rule 3: Redis down
        def check_redis_down() -> bool:
            if not settings.redis_enabled:
                return False
            try:
                result = cache_manager.ping()
                return not result
            except Exception:
                logger.warning("Redis down alert rule check failed", exc_info=True)
                return True

        self.rules.append(AlertRule(
            name="redis_down",
            level="critical",
            condition=check_redis_down,
            message="Redis连接失败",
            channels=["macos", "webhook"]
        ))

        # Rule 4: High memory (>80%)
        def check_high_memory() -> bool:
            try:
                memory = psutil.virtual_memory()
                return memory.percent > 80
            except Exception:
                logger.warning("High memory alert rule check failed", exc_info=True)
                return False

        self.rules.append(AlertRule(
            name="high_memory",
            level="warning",
            condition=check_high_memory,
            message="内存使用超过80%",
            channels=["webhook"]
        ))

        # Rule 5: WebSocket connection limit (>90 connections)
        def check_too_many_connections() -> bool:
            if not settings.prometheus_enabled:
                return False
            try:
                for metric in metrics_collector.registry.collect():
                    if metric.name == 'gold_websocket_connections':
                        for sample in metric.samples:
                            if sample.name == 'gold_websocket_connections':
                                return sample.value > 90
                return False
            except Exception:
                logger.warning("WebSocket connections alert rule check failed", exc_info=True)
                return False

        self.rules.append(AlertRule(
            name="too_many_connections",
            level="warning",
            condition=check_too_many_connections,
            message="WebSocket连接数接近上限",
            channels=["webhook"]
        ))

    def evaluate_rules(self):
        """Evaluate all alert rules and send alerts if conditions are met"""
        for rule in self.rules:
            try:
                if rule.condition():
                    self.send_alert(
                        rule_name=rule.name,
                        level=rule.level,
                        title=rule.name.replace('_', ' ').title(),
                        message=rule.message,
                        channels=rule.channels
                    )
            except Exception as e:
                logger.warning("Error evaluating rule %s: %s", rule.name, e)

        self._evaluate_custom_rules()

    def _evaluate_custom_rules(self):
        now = datetime.now()
        try:
            with get_db_session() as session:
                rules = (
                    session.query(CustomAlertRule)
                    .filter(CustomAlertRule.enabled.is_(True))
                    .all()
                )

                if not rules:
                    return

                indicators = None
                for rule in rules:
                    if not should_trigger_with_cooldown(rule, now):
                        continue

                    result = evaluate_custom_rule(rule, indicators=indicators)
                    if result.metric_value is not None and indicators is None and rule.rule_type.startswith("rsi_"):
                        indicators = {"rsi": result.metric_value}

                    if not result.triggered:
                        continue

                    channels = _safe_load_channels(rule.channels)
                    channel_hint = ", ".join(channels)
                    delivered = self.send_alert(
                        rule_name=f"custom_rule_{rule.id}",
                        level="warning",
                        title=f"Custom Alert: {rule.name}",
                        message=f"{result.message} | channels={channel_hint}",
                        channels=channels,
                    )
                    if delivered:
                        rule.last_triggered_at = now

        except Exception:
            logger.exception("Custom alert evaluation failed")



# 告警规则定义
ALERT_RULES = {
    "collector_failure": {
        "level": "critical",
        "message": "数据采集失败率超过50%",
        "channels": ["macos", "webhook"]
    },
    "price_spike": {
        "level": "warning",
        "message": "价格异常波动超过5%",
        "channels": ["macos"]
    },
    "redis_down": {
        "level": "critical",
        "message": "Redis连接失败",
        "channels": ["macos", "webhook"]
    },
    "high_memory": {
        "level": "warning",
        "message": "内存使用超过80%",
        "channels": ["webhook"]
    },
    "too_many_connections": {
        "level": "warning",
        "message": "WebSocket连接数接近上限",
        "channels": ["webhook"]
    }
}


# 全局告警管理器实例
alert_manager = AlertManager()
