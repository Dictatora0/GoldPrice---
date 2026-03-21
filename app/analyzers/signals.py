from app.analyzers.indicators import IndicatorCalculator
from app.analyzers.decision_engine import evaluate_decision_core
from app.database import get_db_session
from app.market_context import (
    analyze_multi_timeframe,
    build_entry_context,
    check_trend_alignment,
    get_price_momentum,
    is_falling_knife,
)
from app.models import PriceHistory, AnalysisSignal
from datetime import datetime, timedelta
from typing import Optional
import json
import logging
from config import settings
import numpy as np
from app.trading_thresholds import TradingThresholds

logger = logging.getLogger(__name__)


class SignalDetector:
    """买入信号检测器 - 增强版"""

    CACHE_SCHEMA_VERSION = "v3"
    MIN_SIGNAL_DEDUP_WINDOW_SECONDS = TradingThresholds.SIGNAL_DEDUP_MIN_WINDOW_SECONDS
    SIGNAL_DEDUP_RELATIVE_TOLERANCE = TradingThresholds.SIGNAL_DEDUP_RELATIVE_TOLERANCE

    def __init__(self):
        self.calculator = IndicatorCalculator()

    def _get_price_momentum(self, minutes: int = 30) -> dict:
        return get_price_momentum(minutes)

    def _analyze_multi_timeframe(self) -> dict:
        return analyze_multi_timeframe()

    def _check_trend_alignment(self, short, mid, long) -> str:
        """检查多周期趋势是否一致"""
        return check_trend_alignment(short, mid, long)

    def _calculate_dynamic_threshold(self, indicators: dict) -> dict:
        """
        根据市场波动情况动态调整买入阈值

        高波动市场: 更严格的条件
        低波动市场: 适当放宽条件
        """
        volatility = indicators.get("volatility", 0) or 0

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

    @staticmethod
    def _is_falling_knife(indicators: dict, momentum: dict, timeframe: dict) -> bool:
        return is_falling_knife(indicators, momentum, timeframe)

    def _has_recent_similar_signal(self, price_cny_per_gram: float, score: int) -> bool:
        if price_cny_per_gram is None:
            return False

        dedup_window_seconds = max(
            settings.signal_dedup_window_seconds,
            self.MIN_SIGNAL_DEDUP_WINDOW_SECONDS,
        )

        with get_db_session(read_only=True) as session:
            cutoff_time = datetime.now() - timedelta(seconds=dedup_window_seconds)
            recent_signals = (
                session.query(
                    AnalysisSignal.price_cny_per_gram,
                    AnalysisSignal.indicators,
                )
                .filter(AnalysisSignal.timestamp >= cutoff_time)
                .filter(AnalysisSignal.signal_type == "buy")
                .order_by(AnalysisSignal.timestamp.desc())
                .all()
            )

        price_tolerance = max(
            0.5,
            price_cny_per_gram * self.SIGNAL_DEDUP_RELATIVE_TOLERANCE,
        )
        for existing_price, indicators_raw in recent_signals:
            if abs(existing_price - price_cny_per_gram) > price_tolerance:
                continue

            existing_score = None
            if indicators_raw:
                try:
                    existing_score = json.loads(indicators_raw).get("evaluation_score")
                except (json.JSONDecodeError, AttributeError):
                    existing_score = None

            if existing_score is None or abs(existing_score - score) <= 5:
                return True

        return False

    def _evaluate_buy_signal_enhanced(self, indicators: dict) -> dict:
        """
        增强版买入信号评估

        返回详细的评分和原因
        """
        score = 0
        max_score = 100
        reasons = []
        risk_flags = []
        setup_flags = []
        confirmation_flags = []

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
                if abs(macd_histogram) < 0.3:
                    score += 15
                    reasons.append("MACD下跌动能减弱")
                elif abs(macd_histogram) < 0.8:
                    score += 8
                    reasons.append("MACD跌势放缓")
                else:
                    score -= 5
                    reasons.append("MACD下跌动能仍强")
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
                score -= 8  # 中期均线低于长期均线,趋势偏弱

        # 5. 实时动量评分 (15分)
        momentum = self._get_price_momentum(30)
        if momentum["trend"] == "down" and momentum["acceleration"] > 0:
            score += 15
            reasons.append("下跌趋势但开始减速")
        elif momentum["trend"] == "down":
            if momentum["acceleration"] > -0.005:
                score += 3
                reasons.append("价格下跌中,但跌速趋缓")
            else:
                score -= 10
                reasons.append("价格下跌仍在加速")
        elif momentum["trend"] == "up":
            score -= 10  # 上涨中不适合买入

        # 6. 多周期趋势确认 (额外加分)
        timeframe = self._analyze_multi_timeframe()
        entry_context = build_entry_context(indicators, momentum, timeframe)
        setup_flags = entry_context["setup_flags"]
        confirmation_flags = entry_context["confirmation_flags"]
        risk_flags.extend(entry_context["risk_flags"])

        if timeframe["alignment"] == "bearish_aligned":
            if self._is_falling_knife(indicators, momentum, timeframe):
                score -= 20
                reasons.append("多周期下跌共振,暂不抄底")
            else:
                score += 3
                reasons.append("多周期下跌但短线出现钝化")
        elif timeframe["alignment"] == "bullish_aligned":
            if current_price and ma_medium and current_price < ma_medium:
                score += 6
                reasons.append("大趋势仍偏强,回撤后有修复机会")
            else:
                score -= 3
        elif timeframe["short_term"] == "bearish" and timeframe["mid_term"] == "neutral":
            score += 5
            reasons.append("短期下跌,中期震荡")

        if entry_context["entry_ready"]:
            score += 8
            reasons.append("反转确认形成")
        elif len(setup_flags) >= 2:
            score -= 12
            reasons.append("超卖条件具备,但反转确认不足")

        return {
            "score": min(score, max_score),
            "max_score": max_score,
            "reasons": reasons,
            "thresholds": thresholds,
            "momentum": momentum,
            "timeframe": timeframe,
            "risk_flags": risk_flags,
            "setup_flags": setup_flags,
            "confirmation_flags": confirmation_flags,
            "entry_ready": entry_context["entry_ready"],
        }

    @staticmethod
    def _attach_unified_decision(evaluation: dict, indicators: dict) -> dict:
        """将统一决策内核结果附加到信号评估，保证各模块口径一致。"""
        unified = evaluate_decision_core(
            indicators,
            momentum=evaluation.get("momentum"),
            timeframe=evaluation.get("timeframe"),
        )

        merged = dict(evaluation)
        merged["entry_ready"] = unified["entry_ready"]
        merged["entry_weak"] = unified.get("entry_weak", False)
        merged["setup_flags"] = unified["setup_flags"]
        merged["confirmation_flags"] = unified["confirmation_flags"]
        merged["risk_flags"] = unified["risk_flags"]
        merged["regime"] = unified["regime"]
        merged["upside_probability"] = unified["upside_probability"]
        merged["downside_risk_bp"] = unified["downside_risk_bp"]
        merged["expected_return_bp"] = unified["expected_return_bp"]
        merged["suggested_position_pct"] = unified["suggested_position_pct"]
        return merged

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
        evaluation = self._attach_unified_decision(evaluation, indicators)
        score = evaluation["score"]

        logger.info(
            "Enhanced buy signal evaluated: score=%d/%d, reasons=%s",
            score,
            evaluation["max_score"],
            ", ".join(evaluation["reasons"])
        )

        # 评分>=70分触发买入信号
        if score >= 70:
            if "falling_knife" in evaluation.get("risk_flags", []):
                logger.info("Falling-knife risk detected, skip signal creation")
                return False

            if not evaluation.get("entry_ready", False):
                logger.info("Buy setup present but confirmation is insufficient, skip signal creation")
                return False

            # 额外确认:检查趋势和波动率
            df = self.calculator.get_price_data(days=10)
            if not df.empty:
                daily_prices = df["price"].resample("1D").last().dropna().tolist()
                if len(daily_prices) >= 6:
                    if not self.is_downtrend_volatility_contracting(daily_prices):
                        logger.info("Trend/volatility condition not met, score reduced")
                        score -= 10  # 降低评分但不完全否决

            if score >= 65:  # 降低后仍然>=65分则触发
                if self._has_recent_similar_signal(indicators["current_price"], score):
                    logger.info("Skip duplicate buy signal near ¥%.2f within dedup window", indicators["current_price"])
                    return False

                evaluation["score"] = score
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
                "risk_flags": evaluation.get("risk_flags", []),
                "setup_flags": evaluation.get("setup_flags", []),
                "confirmation_flags": evaluation.get("confirmation_flags", []),
                "entry_ready": evaluation.get("entry_ready", False),
                "entry_weak": evaluation.get("entry_weak", False),
                "regime": evaluation.get("regime"),
                "upside_probability": evaluation.get("upside_probability"),
                "downside_risk_bp": evaluation.get("downside_risk_bp"),
                "expected_return_bp": evaluation.get("expected_return_bp"),
                "suggested_position_pct": evaluation.get("suggested_position_pct"),
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
        with get_db_session(read_only=True) as session:
            signal = session.query(AnalysisSignal)\
                .filter(AnalysisSignal.notified.is_(False))\
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
        with get_db_session(read_only=True) as session:
            last_notification = session.query(AnalysisSignal).filter(
                AnalysisSignal.notified.is_(True),
                AnalysisSignal.timestamp
                > datetime.now() - timedelta(hours=settings.notification_cooldown)
            ).first()

            return last_notification is None

    def mark_notified(self):
        """标记最新信号已通知"""
        with get_db_session() as session:
            latest_signal = session.query(AnalysisSignal).filter(
                AnalysisSignal.notified.is_(False)
            ).order_by(AnalysisSignal.timestamp.desc()).first()

            if latest_signal:
                latest_signal.notified = True
                session.commit()

    def evaluate_buy_signal_cached(self) -> Optional[dict]:
        """评估买入信号(带缓存)"""
        from app.cache import cache_manager
        from config import settings

        with get_db_session(read_only=True) as session:
            latest = session.query(PriceHistory.timestamp).order_by(
                PriceHistory.timestamp.desc()
            ).first()

            if not latest:
                indicators = self.calculator.calculate_all()
                if not indicators:
                    return None
                return self._attach_unified_decision(
                    self._evaluate_buy_signal_enhanced(indicators),
                    indicators,
                )

            cache_key = f"signals:{self.CACHE_SCHEMA_VERSION}:{latest[0].isoformat()}"

        cached = cache_manager.get(cache_key)
        if cached:
            if isinstance(cached, str):
                try:
                    return json.loads(cached)
                except json.JSONDecodeError:
                    pass
            return cached

        indicators = self.calculator.calculate_all()
        if not indicators:
            return None

        result = self._attach_unified_decision(
            self._evaluate_buy_signal_enhanced(indicators),
            indicators,
        )
        cache_manager.set(
            cache_key,
            json.dumps(result, default=str),
            ttl=settings.cache_signals_ttl,
        )

        return result
