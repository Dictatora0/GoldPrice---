from app.analyzers.indicators import IndicatorCalculator
from app.database import get_db_session
from app.models import PriceHistory, AnalysisSignal
from datetime import datetime, timedelta
from typing import Optional
import json
import logging
from config import settings
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class SignalDetector:
    """买入信号检测器 - 增强版"""

    def __init__(self):
        self.calculator = IndicatorCalculator()

    def _get_price_momentum(self, minutes: int = 30) -> dict:
        """
        分析最近N分钟的价格动量

        返回:
        - change_pct: 价格变化百分比
        - trend: 趋势方向 (up/down/flat)
        - acceleration: 加速度(正值表示加速上涨或减速下跌)
        """
        with get_db_session() as session:
            cutoff_time = datetime.now() - timedelta(minutes=minutes)
            prices = session.query(PriceHistory)\
                .filter(PriceHistory.timestamp >= cutoff_time)\
                .order_by(PriceHistory.timestamp.asc())\
                .all()

            if len(prices) < 3:
                return {"change_pct": 0, "trend": "flat", "acceleration": 0}

            price_values = [p.price_cny_per_gram for p in prices]
            first_price = price_values[0]
            last_price = price_values[-1]

            # 价格变化百分比
            change_pct = ((last_price - first_price) / first_price) * 100

            # 趋势判断
            if change_pct > 0.1:
                trend = "up"
            elif change_pct < -0.1:
                trend = "down"
            else:
                trend = "flat"

            # 计算加速度(最近一半 vs 前一半的变化率)
            mid = len(price_values) // 2
            first_half_change = (price_values[mid] - price_values[0]) / price_values[0]
            second_half_change = (price_values[-1] - price_values[mid]) / price_values[mid]
            acceleration = second_half_change - first_half_change

            return {
                "change_pct": change_pct,
                "trend": trend,
                "acceleration": acceleration
            }

    def _analyze_multi_timeframe(self) -> dict:
        """
        多时间周期分析

        返回各时间周期的趋势状态
        """
        with get_db_session() as session:
            now = datetime.now()

            # 短期(1小时)
            short_term = session.query(PriceHistory)\
                .filter(PriceHistory.timestamp >= now - timedelta(hours=1))\
                .order_by(PriceHistory.timestamp.asc())\
                .all()

            # 中期(6小时)
            mid_term = session.query(PriceHistory)\
                .filter(PriceHistory.timestamp >= now - timedelta(hours=6))\
                .order_by(PriceHistory.timestamp.asc())\
                .all()

            # 长期(24小时)
            long_term = session.query(PriceHistory)\
                .filter(PriceHistory.timestamp >= now - timedelta(hours=24))\
                .order_by(PriceHistory.timestamp.asc())\
                .all()

            def get_trend(prices):
                if len(prices) < 2:
                    return "unknown"
                first = prices[0].price_cny_per_gram
                last = prices[-1].price_cny_per_gram
                change = ((last - first) / first) * 100

                if change > 0.5:
                    return "bullish"
                elif change < -0.5:
                    return "bearish"
                else:
                    return "neutral"

            return {
                "short_term": get_trend(short_term),
                "mid_term": get_trend(mid_term),
                "long_term": get_trend(long_term),
                "alignment": self._check_trend_alignment(
                    get_trend(short_term),
                    get_trend(mid_term),
                    get_trend(long_term)
                )
            }

    def _check_trend_alignment(self, short, mid, long) -> str:
        """检查多周期趋势是否一致"""
        trends = [short, mid, long]

        if trends.count("bearish") >= 2:
            return "bearish_aligned"
        elif trends.count("bullish") >= 2:
            return "bullish_aligned"
        else:
            return "mixed"

    def _calculate_dynamic_threshold(self, indicators: dict) -> dict:
        """
        根据市场波动情况动态调整买入阈值

        高波动市场: 更严格的条件
        低波动市场: 适当放宽条件
        """
        volatility = indicators.get("volatility", 0)
        rsi = indicators.get("rsi", 50)

        # 基础阈值
        base_rsi_threshold = 30
        base_bb_threshold = 1.0  # 价格需低于布林带下轨的倍数

        # 根据波动率调整
        if volatility > 5:  # 高波动
            rsi_threshold = 25  # 更严格
            bb_threshold = 1.02
        elif volatility < 2:  # 低波动
            rsi_threshold = 35  # 适当放宽
            bb_threshold = 0.98
        else:
            rsi_threshold = base_rsi_threshold
            bb_threshold = base_bb_threshold

        return {
            "rsi_threshold": rsi_threshold,
            "bb_threshold": bb_threshold,
            "volatility_level": "high" if volatility > 5 else "low" if volatility < 2 else "normal"
        }

    def _evaluate_buy_signal_enhanced(self, indicators: dict) -> dict:
        """
        增强版买入信号评估

        返回详细的评分和原因
        """
        score = 0
        max_score = 100
        reasons = []

        current_price = indicators.get("current_price")
        rsi = indicators.get("rsi")
        bb_lower = indicators.get("bb_lower")
        bb_middle = indicators.get("bb_middle")
        ma_medium = indicators.get("ma_medium")
        ma_long = indicators.get("ma_long")
        macd = indicators.get("macd")
        macd_signal = indicators.get("macd_signal")
        macd_histogram = indicators.get("macd_histogram")

        # 动态阈值
        thresholds = self._calculate_dynamic_threshold(indicators)

        # 1. RSI超卖评分 (25分)
        if rsi is not None:
            if rsi < 20:
                score += 25
                reasons.append(f"RSI极度超卖({rsi:.1f})")
            elif rsi < thresholds["rsi_threshold"]:
                score += 20
                reasons.append(f"RSI超卖({rsi:.1f})")
            elif rsi < 40:
                score += 10
                reasons.append(f"RSI偏低({rsi:.1f})")

        # 2. 布林带位置评分 (25分)
        if current_price and bb_lower and bb_middle:
            if current_price < bb_lower * thresholds["bb_threshold"]:
                score += 25
                reasons.append("价格突破布林带下轨")
            elif current_price < bb_middle:
                distance = (bb_middle - current_price) / bb_middle * 100
                distance_score = int(15 * (distance / 2))
                score += distance_score
                reasons.append(f"价格低于布林带中轨{distance:.1f}%")

        # 3. MACD动量评分 (20分)
        if macd is not None and macd_signal is not None and macd_histogram is not None:
            if macd < macd_signal and macd_histogram < 0:
                # 死叉但柱状图收窄(下跌动能减弱)
                if abs(macd_histogram) < 0.5:
                    score += 15
                    reasons.append("MACD下跌动能减弱")
                else:
                    score += 5
            elif macd > macd_signal and macd_histogram > 0:
                # 金叉(上涨动能)
                score += 20
                reasons.append("MACD金叉形成")

        # 4. 均线位置评分 (15分)
        if current_price and ma_medium and ma_long:
            if current_price < ma_medium * 0.95:
                score += 15
                reasons.append("价格远低于中期均线")
            elif current_price < ma_medium * 0.98:
                score += 10
                reasons.append("价格低于中期均线")

            # 均线排列
            if ma_medium < ma_long:
                score -= 5  # 中期均线低于长期均线,趋势偏弱

        # 5. 实时动量评分 (15分)
        momentum = self._get_price_momentum(30)
        if momentum["trend"] == "down" and momentum["acceleration"] > 0:
            score += 15
            reasons.append("下跌趋势但开始减速")
        elif momentum["trend"] == "down":
            score += 5
            reasons.append("价格下跌中")
        elif momentum["trend"] == "up":
            score -= 10  # 上涨中不适合买入

        # 6. 多周期趋势确认 (额外加分)
        timeframe = self._analyze_multi_timeframe()
        if timeframe["alignment"] == "bearish_aligned":
            score += 10
            reasons.append("多周期下跌趋势一致")
        elif timeframe["short_term"] == "bearish" and timeframe["mid_term"] == "neutral":
            score += 5
            reasons.append("短期下跌,中期震荡")

        return {
            "score": min(score, max_score),
            "max_score": max_score,
            "reasons": reasons,
            "thresholds": thresholds,
            "momentum": momentum,
            "timeframe": timeframe
        }

    @staticmethod
    def evaluate_buy_signal(indicators: dict) -> bool:
        """
        根据指标判断是否满足买入条件(保留向后兼容)
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
        检测是否满足买入条件 - 增强版

        使用新的评分系统,当评分>=70分时触发买入信号
        """
        indicators = self.calculator.calculate_all()

        if not indicators:
            logger.warning("Insufficient data for signal detection")
            return False

        # 使用增强版评估
        evaluation = self._evaluate_buy_signal_enhanced(indicators)
        score = evaluation["score"]

        logger.info(
            "Enhanced buy signal evaluated: score=%d/%d, reasons=%s",
            score,
            evaluation["max_score"],
            ", ".join(evaluation["reasons"])
        )

        # 评分>=70分触发买入信号
        if score >= 70:
            # 额外确认:检查趋势和波动率
            df = self.calculator.get_price_data(days=10)
            if not df.empty:
                daily_prices = df["price"].resample("1D").last().dropna().tolist()
                if len(daily_prices) >= 6:
                    if not self.is_downtrend_volatility_contracting(daily_prices):
                        logger.info("Trend/volatility condition not met, score reduced")
                        score -= 10  # 降低评分但不完全否决

            if score >= 65:  # 降低后仍然>=65分则触发
                self._save_signal(indicators, evaluation)
                return True

        return False

    def _save_signal(self, indicators: dict, evaluation: dict):
        """保存买入信号到数据库"""
        with get_db_session() as session:
            # 合并指标和评估结果
            signal_data = {
                **indicators,
                "evaluation_score": evaluation["score"],
                "evaluation_reasons": evaluation["reasons"],
                "momentum": evaluation["momentum"],
                "timeframe_analysis": evaluation["timeframe"]
            }

            signal = AnalysisSignal(
                timestamp=datetime.now(),
                signal_type="buy",
                price_cny_per_gram=indicators["current_price"],
                indicators=json.dumps(signal_data, ensure_ascii=False),
                notified=False
            )
            session.add(signal)
            session.commit()
            logger.info(
                f"Enhanced buy signal saved: ¥{indicators['current_price']}/g, "
                f"score={evaluation['score']}, reasons={', '.join(evaluation['reasons'])}"
            )

    def get_latest_signal(self) -> Optional[dict]:
        """获取最新的买入信号详情"""
        with get_db_session() as session:
            signal = session.query(AnalysisSignal)\
                .filter(AnalysisSignal.notified == False)\
                .order_by(AnalysisSignal.timestamp.desc())\
                .first()

            if not signal:
                return None

            indicators = json.loads(signal.indicators) if signal.indicators else {}

            return {
                "price_cny_per_gram": signal.price_cny_per_gram,
                "indicators": indicators,
                "timestamp": signal.timestamp.isoformat()
            }

    def should_notify(self) -> bool:
        """检查是否应该发送通知(24小时内未通知过)"""
        with get_db_session() as session:
            last_notification = session.query(AnalysisSignal).filter(
                AnalysisSignal.notified == True,
                AnalysisSignal.timestamp
                > datetime.now() - timedelta(hours=settings.notification_cooldown)
            ).first()

            return last_notification is None

    def mark_notified(self):
        """标记最新信号已通知"""
        with get_db_session() as session:
            latest_signal = session.query(AnalysisSignal).filter(
                AnalysisSignal.notified == False
            ).order_by(AnalysisSignal.timestamp.desc()).first()

            if latest_signal:
                latest_signal.notified = True
                session.commit()

    def evaluate_buy_signal_cached(self) -> Optional[dict]:
        """评估买入信号(带缓存)"""
        from app.cache import cache_manager
        from config import settings
        from app.database import get_db_session
        from app.models import PriceSource

        with get_db_session() as session:
            latest = session.query(PriceSource).order_by(
                PriceSource.timestamp.desc()
            ).first()

            if not latest:
                indicators = self.calculator.calculate_all()
                if not indicators:
                    return None
                return self._evaluate_buy_signal_enhanced(indicators)

            cache_key = f"signals:{latest.timestamp.isoformat()}"

        cached = cache_manager.get(cache_key)
        if cached:
            return cached

        indicators = self.calculator.calculate_all()
        if not indicators:
            return None

        result = self._evaluate_buy_signal_enhanced(indicators)
        cache_manager.set(cache_key, result, ttl=settings.cache_signals_ttl)

        return result
