from app.analyzers.indicators import IndicatorCalculator
from app.database import get_session
from app.models import AnalysisSignal
from datetime import datetime, timedelta
import json
import logging
from config import settings
import numpy as np

logger = logging.getLogger(__name__)


class SignalDetector:
    """买入信号检测器"""

    def __init__(self):
        self.calculator = IndicatorCalculator()

    @staticmethod
    def evaluate_buy_signal(indicators: dict) -> bool:
        """
        根据指标判断是否满足买入条件

        条件:
        1. 当前价格低于布林带下轨
        2. RSI < 30
        3. 当前价格低于30天均线2%以上
        4. 波动率较低(作为收窄的简化判断)
        """
        current_price = indicators.get("current_price")
        rsi = indicators.get("rsi")
        bb_lower = indicators.get("bb_lower")
        ma_medium = indicators.get("ma_medium")

        if None in [current_price, rsi, bb_lower, ma_medium]:
            return False

        condition1 = current_price < bb_lower
        condition2 = rsi < 30
        condition3 = current_price < ma_medium * 0.98

        volatility = indicators.get("volatility")
        if volatility is None:
            return False
        condition4 = volatility < ma_medium * 0.02

        return all([condition1, condition2, condition3, condition4])

    @staticmethod
    def is_downtrend_volatility_contracting(prices: list) -> bool:
        """
        判断最近3个周期是否下行且波动率收窄
        使用最近6个点: 前3个 vs 后3个
        """
        if len(prices) < 6:
            return False

        previous = prices[-6:-3]
        recent = prices[-3:]

        # 最近3个点呈下降趋势
        if not (recent[0] > recent[1] > recent[2]):
            return False

        return float(np.std(recent)) < float(np.std(previous))

    def check_buy_signal(self) -> bool:
        """
        检测是否满足买入条件

        买入信号条件:
        1. 当前价格低于布林带下轨
        2. RSI < 30 (超卖)
        3. 当前价格低于30天均线2%以上
        4. 最近3天价格呈下降趋势但波动率开始收窄
        """
        indicators = self.calculator.calculate_all()

        if not indicators:
            logger.warning("Insufficient data for signal detection")
            return False

        meets_conditions = self.evaluate_buy_signal(indicators)
        logger.info(
            "Buy signal evaluated: %s",
            "pass" if meets_conditions else "fail",
        )

        if meets_conditions:
            df = self.calculator.get_price_data(days=10)
            if df.empty:
                logger.warning("Insufficient data for trend analysis")
                return False

            daily_prices = (
                df["price"].resample("1D").last().dropna().tolist()
            )
            if not self.is_downtrend_volatility_contracting(daily_prices):
                logger.info("Trend/volatility condition not met")
                return False

            self._save_signal(indicators)
            return True

        return False

    def _save_signal(self, indicators: dict):
        """保存买入信号到数据库"""
        session = get_session()
        try:
            signal = AnalysisSignal(
                timestamp=datetime.now(),
                signal_type="buy",
                price_cny_per_gram=indicators["current_price"],
                indicators=json.dumps(indicators),
                notified=False
            )
            session.add(signal)
            session.commit()
            logger.info(f"Buy signal saved: ¥{indicators['current_price']}/g")
        finally:
            session.close()

    def should_notify(self) -> bool:
        """检查是否应该发送通知(24小时内未通知过)"""
        session = get_session()
        try:
            last_notification = session.query(AnalysisSignal).filter(
                AnalysisSignal.notified == True,
                AnalysisSignal.timestamp
                > datetime.now() - timedelta(hours=settings.notification_cooldown)
            ).first()

            return last_notification is None
        finally:
            session.close()

    def mark_notified(self):
        """标记最新信号已通知"""
        session = get_session()
        try:
            latest_signal = session.query(AnalysisSignal).filter(
                AnalysisSignal.notified == False
            ).order_by(AnalysisSignal.timestamp.desc()).first()

            if latest_signal:
                latest_signal.notified = True
                session.commit()
        finally:
            session.close()
