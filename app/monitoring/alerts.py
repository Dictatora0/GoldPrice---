import apprise
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict

from config import settings


class AlertManager:
    """告警管理器"""

    def __init__(self):
        self.apprise = apprise.Apprise()
        self.last_alert_time: Dict[str, datetime] = defaultdict(lambda: datetime.min)

        # 配置通知渠道
        if settings.enable_notification:
            self.apprise.add('macos://')

        if settings.alert_webhook_url:
            self.apprise.add(settings.alert_webhook_url)

        if settings.alert_slack_webhook:
            self.apprise.add(f'slack://{settings.alert_slack_webhook}')

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
