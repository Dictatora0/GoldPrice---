import logging
from typing import Dict

try:
    import pync
except ModuleNotFoundError:  # pragma: no cover
    pync = None

from config import settings

logger = logging.getLogger(__name__)


class MacOSNotifier:
    """macOS 通知"""

    def notify_buy_signal(self, price: float, indicators: Dict):
        if not settings.enable_notification:
            return False
        if pync is None:
            logger.error("pync not installed; notification skipped")
            return False

        rsi = indicators.get("rsi")
        ma_medium = indicators.get("ma_medium")
        drop_percent = None
        if ma_medium:
            drop_percent = (price - ma_medium) / ma_medium * 100

        message_lines = [f"当前价格: ¥{price:.2f}/克"]
        if drop_percent is not None:
            message_lines.append(f"跌幅: {drop_percent:.2f}% (相比30天均价)")
        if rsi is not None:
            message_lines.append(f"RSI: {rsi:.2f}")
        message_lines.append("建议: 价格触及低位,注意机会")

        message = "\n".join(message_lines)

        try:
            pync.notify(
                title="黄金价格买入提醒",
                message=message,
                sound="default",
            )
            logger.info("Notification sent")
            return True
        except Exception as exc:
            logger.error("Notification failed: %s", exc)
            return False
