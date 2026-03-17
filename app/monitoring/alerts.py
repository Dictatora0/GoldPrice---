import apprise
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass

from config import settings


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
        self.last_alert_time: Dict[str, datetime] = defaultdict(lambda: datetime.min)
        self.rules: List[AlertRule] = []

        # 配置通知渠道
        if settings.enable_notification:
            self.apprise.add('macos://')

        if settings.alert_webhook_url:
            self.apprise.add(settings.alert_webhook_url)

        if settings.alert_slack_webhook:
            self.apprise.add(f'slack://{settings.alert_slack_webhook}')

        # Initialize alert rules
        self._init_rules()

    def send_alert(self, rule_name: str, level: str, title: str, message: str, channels: Optional[List[str]] = None):
        """发送告警"""
        # 检查冷却时间
        if not self._should_send_alert(rule_name):
            return

        # 发送通知
        try:
            self.apprise.notify(
                title=f"[{level.upper()}] {title}",
                body=message
            )
            self.last_alert_time[rule_name] = datetime.now()
        except Exception as e:
            print(f"Failed to send alert: {e}")

    def _should_send_alert(self, rule_name: str) -> bool:
        """检查是否应该发送告警(冷却时间)"""
        last_time = self.last_alert_time.get(rule_name, datetime.min)
        cooldown = timedelta(minutes=settings.alert_cooldown_minutes)
        return datetime.now() - last_time > cooldown

    def _init_rules(self):
        """Initialize alert rules"""
        from app.monitoring.metrics import metrics_collector
        from app.cache import cache_manager
        from app.database import get_session
        from app.models import PriceHistory
        import psutil

        # Rule 1: Collector failure (>50% failure rate)
        def check_collector_failure() -> bool:
            if not settings.prometheus_enabled:
                return False
            try:
                # Get metrics from registry
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
                session = get_session()
                one_hour_ago = datetime.now() - timedelta(hours=1)

                # Get current price
                current = session.query(PriceHistory)\
                    .order_by(PriceHistory.timestamp.desc())\
                    .first()

                # Get price from 1 hour ago
                old = session.query(PriceHistory)\
                    .filter(PriceHistory.timestamp <= one_hour_ago)\
                    .order_by(PriceHistory.timestamp.desc())\
                    .first()

                session.close()

                if current and old and old.price > 0:
                    change_pct = abs((current.price - old.price) / old.price)
                    return change_pct > 0.05
                return False
            except Exception:
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
                import asyncio
                result = asyncio.run(cache_manager.ping())
                return not result
            except Exception:
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
                print(f"Error evaluating rule {rule.name}: {e}")



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
