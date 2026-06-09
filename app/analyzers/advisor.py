import json
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from app.analyzers.decision_engine import evaluate_decision_core
from app.analyzers.position import build_current_position_advice, get_position_state
from app.analyzers.indicators import IndicatorCalculator
from app.database import get_db_session
from app.market_indicators import MarketIndicators
from app.market_context import (
    analyze_multi_timeframe,
    build_entry_context,
    get_price_momentum,
    is_falling_knife,
)
from app.price_regime import filter_current_regime
from app.price_regime import build_regime_meta
from app.models import PriceHistory, AdviceSnapshot
from app.trading_thresholds import TradingThresholds
from app.cache import build_cache_key, get_json_cache, set_json_cache


class MarketAdvisor:
    """市场智能顾问 - 基于多指标综合分析提供买入建议(增强版)"""

    CACHE_SCHEMA_VERSION = "v6"

    def __init__(self):
        self.calculator = IndicatorCalculator()

    def _get_price_trend_analysis(self) -> Dict:
        """
        分析最近的价格趋势变化

        返回:
        - recent_change: 最近1小时变化
        - today_change: 今日变化
        - momentum: 动量状态
        """
        with get_db_session(read_only=True) as session:
            now = datetime.now()

            # 最近1小时
            hour_ago = now - timedelta(hours=1)
            recent_prices = session.query(PriceHistory)\
                .filter(PriceHistory.timestamp >= hour_ago)\
                .order_by(PriceHistory.timestamp.asc())\
                .all()

            # 今日价格
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_prices = session.query(PriceHistory)\
                .filter(PriceHistory.timestamp >= today_start)\
                .order_by(PriceHistory.timestamp.asc())\
                .all()

            recent_prices = filter_current_regime(
                recent_prices,
                price_getter=lambda row: row.price_cny_per_gram,
            )
            today_prices = filter_current_regime(
                today_prices,
                price_getter=lambda row: row.price_cny_per_gram,
            )

            result = {
                "recent_change": 0,
                "today_change": 0,
                "momentum": "neutral"
            }

            if len(recent_prices) >= 2:
                first = recent_prices[0].price_cny_per_gram
                last = recent_prices[-1].price_cny_per_gram
                result["recent_change"] = ((last - first) / first) * 100

            if len(today_prices) >= 2:
                first = today_prices[0].price_cny_per_gram
                last = today_prices[-1].price_cny_per_gram
                result["today_change"] = ((last - first) / first) * 100

            # 动量判断
            if result["recent_change"] > 0.3:
                result["momentum"] = "strong_up"
            elif result["recent_change"] > 0.1:
                result["momentum"] = "up"
            elif result["recent_change"] < -0.3:
                result["momentum"] = "strong_down"
            elif result["recent_change"] < -0.1:
                result["momentum"] = "down"

            return result

    def _calculate_score(self, indicators: Dict) -> int:
        """计算综合评分 (0-100分,越低越适合买入)"""
        score = TradingThresholds.SCORE_BASELINE
        risk_flags = set(indicators.get('_risk_flags', []))
        momentum = indicators.get('_momentum_context') or {}
        timeframe = indicators.get('_timeframe_context') or {}
        entry_context = self._get_entry_context(indicators)
        typed = MarketIndicators.from_dict(indicators)

        rsi = typed.rsi
        price = typed.current_price
        bb_lower = typed.bb_lower
        bb_middle = typed.bb_middle
        bb_upper = typed.bb_upper
        ma_medium = typed.ma_medium
        ma_long = typed.ma_long
        macd = typed.macd
        macd_signal = typed.macd_signal
        macd_histogram = typed.macd_histogram

        if not risk_flags and momentum and timeframe and is_falling_knife(indicators, momentum, timeframe):
            risk_flags.add('falling_knife')

        # RSI 评分 (权重 30%)
        if rsi is not None:
            if rsi < TradingThresholds.RSI_OVERSOLD:
                score += TradingThresholds.RSI_SCORE_OVERSOLD
            elif rsi < 40:
                score += TradingThresholds.RSI_SCORE_MILD_OVERSOLD
            elif rsi > TradingThresholds.RSI_OVERBOUGHT:
                score += TradingThresholds.RSI_SCORE_OVERBOUGHT
            elif rsi > TradingThresholds.RSI_OVERBOUGHT_MILD:
                score += TradingThresholds.RSI_SCORE_MILD_OVERBOUGHT

        # 布林带位置 (权重 25%)
        if price and bb_lower and bb_middle and bb_upper:
            band_width = typed.bollinger_band_width_ratio()
            if price < bb_lower:
                break_depth = typed.bollinger_break_depth_ratio() or 0.0
                if band_width is not None and band_width < TradingThresholds.BB_NARROW_BAND_WIDTH:
                    score += (
                        TradingThresholds.BB_SCORE_BREAK_NARROW
                        - int(break_depth * TradingThresholds.BB_BREAK_DEPTH_MULTIPLIER_NARROW)
                    )
                else:
                    score += (
                        TradingThresholds.BB_SCORE_BREAK_WIDE
                        - int(break_depth * TradingThresholds.BB_BREAK_DEPTH_MULTIPLIER_WIDE)
                    )
            elif price < bb_middle:
                score += TradingThresholds.BB_SCORE_BELOW_MIDDLE
            elif price > bb_upper:
                score += TradingThresholds.BB_SCORE_ABOVE_UPPER
            elif price > bb_middle:
                score += TradingThresholds.BB_SCORE_ABOVE_MIDDLE

        # MACD (权重 25%)
        if macd is not None and macd_signal is not None and macd_histogram is not None:
            if macd > macd_signal and macd_histogram > 0:
                score += TradingThresholds.MACD_SCORE_GOLDEN_CROSS
            elif macd < macd_signal and macd_histogram < 0:
                score += TradingThresholds.MACD_SCORE_DEATH_CROSS

            # 柱状图变化趋势
            if abs(macd_histogram) < 0.1:
                score -= 3  # 动量减弱,可能反转

        # MA 趋势 (权重 20%)
        if price and ma_medium:
            deviation = (price - ma_medium) / ma_medium * 100
            if deviation < -2:
                score -= 10  # 价格远低于均线
            elif deviation > 2:
                score += 10  # 价格远高于均线

        if price and ma_medium and ma_long and ma_medium < ma_long:
            score += 8

        if 'falling_knife' in risk_flags:
            confirmation_count = len(entry_context.get('confirmation_flags', []))
            if entry_context.get('entry_ready', False):
                score += TradingThresholds.FALLING_KNIFE_PENALTY_ENTRY_READY
            elif confirmation_count >= 2:
                score += TradingThresholds.FALLING_KNIFE_PENALTY_CONFIRMED
            else:
                score += TradingThresholds.FALLING_KNIFE_PENALTY_UNCONFIRMED

        if len(entry_context.get('setup_flags', [])) >= 2 and not entry_context.get('entry_ready', False):
            score += 18

        if entry_context.get('entry_ready', False):
            score -= 6

        # 确保分数在 0-100 范围内
        return max(0, min(100, score))

    def _get_recommendation(self, score: int) -> str:
        """根据评分生成建议"""
        if score <= 25:
            return "强烈推荐买入"
        elif score <= 40:
            return "推荐买入"
        elif score <= 60:
            return "观望"
        elif score <= 75:
            return "不推荐"
        else:
            return "强烈不推荐"

    def _align_recommendation_with_entry_context(self, recommendation: str, indicators: Dict) -> str:
        """确保综合建议与入场确认状态保持一致，避免前后矛盾。"""
        risk_flags = set(indicators.get('_risk_flags', []))
        entry_context = self._get_entry_context(indicators)
        entry_ready = entry_context.get('entry_ready', False)
        entry_weak = entry_context.get('entry_weak', False)

        if 'falling_knife' in risk_flags and recommendation in {"强烈推荐买入", "推荐买入", "观望"}:
            return "不推荐"

        if not entry_ready and recommendation in {"强烈推荐买入", "推荐买入"}:
            return "观望"

        if recommendation == "强烈推荐买入" and entry_weak:
            return "推荐买入"

        return recommendation

    def _describe_market_state(self, indicators: Dict) -> str:
        """描述市场状态"""
        risk_flags = set(indicators.get('_risk_flags', []))
        entry_context = self._get_entry_context(indicators)
        rsi = indicators.get('rsi')
        price = indicators.get('current_price')
        bb_lower = indicators.get('bb_lower')
        bb_upper = indicators.get('bb_upper')
        ma_medium = indicators.get('ma_medium')
        macd = indicators.get('macd')
        macd_signal = indicators.get('macd_signal')

        states = []

        # 趋势判断
        if price and ma_medium:
            if price > ma_medium * 1.02:
                states.append("价格处于上升趋势")
            elif price < ma_medium * 0.98:
                states.append("价格处于下降趋势")
            else:
                states.append("价格处于震荡区间")

        # 超买超卖
        if rsi is not None:
            if rsi < 30:
                states.append("接近超卖区")
            elif rsi > 70:
                states.append("接近超买区")

        # 布林带位置
        if price and bb_lower and bb_upper:
            if price < bb_lower:
                states.append("价格触及布林带下轨")
            elif price > bb_upper:
                states.append("价格触及布林带上轨")

        # MACD 状态
        if macd is not None and macd_signal is not None:
            if macd > macd_signal:
                states.append("MACD 呈金叉形态")
            else:
                states.append("MACD 呈死叉形态")

        if 'falling_knife' in risk_flags:
            states.insert(0, "市场处于飞刀式下跌阶段")
        elif len(entry_context.get('setup_flags', [])) >= 2 and not entry_context.get('entry_ready', False):
            states.insert(0, "入场形态已出现但反转确认不足,当前更适合观察")

        return "，".join(states) if states else "市场状态正常"

    def _generate_insights(self, indicators: Dict) -> List[str]:
        """生成关键洞察(增强版)"""
        insights = []
        risk_flags = set(indicators.get('_risk_flags', []))

        rsi = indicators.get('rsi')
        price = indicators.get('current_price')
        bb_lower = indicators.get('bb_lower')
        bb_upper = indicators.get('bb_upper')
        bb_middle = indicators.get('bb_middle')
        ma_medium = indicators.get('ma_medium')
        macd = indicators.get('macd')
        macd_signal = indicators.get('macd_signal')
        macd_histogram = indicators.get('macd_histogram')
        volatility = indicators.get('volatility')

        # 获取实时价格趋势
        trend_analysis = self._get_price_trend_analysis()

        if 'falling_knife' in risk_flags:
            insights.append("⚠️ 当前处于下跌共振阶段,超卖不等于止跌,不宜贸然抄底")

        # 实时动量洞察
        if trend_analysis["momentum"] == "strong_down":
            insights.append(f"⚠️ 最近1小时价格下跌{abs(trend_analysis['recent_change']):.2f}%,下跌动能较强")
        elif trend_analysis["momentum"] == "down":
            insights.append(f"📉 最近1小时价格下跌{abs(trend_analysis['recent_change']):.2f}%")
        elif trend_analysis["momentum"] == "strong_up":
            insights.append(f"📈 最近1小时价格上涨{trend_analysis['recent_change']:.2f}%,上涨动能强劲")
        elif trend_analysis["momentum"] == "up":
            insights.append(f"↗️ 最近1小时价格上涨{trend_analysis['recent_change']:.2f}%")

        # 今日表现
        if abs(trend_analysis["today_change"]) > 0.5:
            direction = "上涨" if trend_analysis["today_change"] > 0 else "下跌"
            insights.append(f"📊 今日累计{direction}{abs(trend_analysis['today_change']):.2f}%")

        # RSI 洞察
        if rsi is not None:
            if rsi < 30:
                if 'falling_knife' in risk_flags:
                    insights.append(f"🔴 RSI {rsi:.1f} 虽处超卖区,但下跌动能未止")
                else:
                    insights.append(f"🔴 RSI {rsi:.1f} 处于超卖区,历史上常出现反弹机会")
            elif rsi < 40:
                insights.append(f"🟡 RSI {rsi:.1f} 接近超卖区,可关注买入时机")
            elif rsi > 70:
                insights.append(f"🔴 RSI {rsi:.1f} 处于超买区,需警惕回调风险")
            elif rsi > 60:
                insights.append(f"🟡 RSI {rsi:.1f} 接近超买区,建议谨慎")

        # 布林带洞察(增强版)
        if price and bb_lower and bb_upper and bb_middle:
            bb_position = (price - bb_lower) / (bb_upper - bb_lower) * 100

            if price < bb_lower:
                if 'falling_knife' in risk_flags:
                    insights.append(f"⚠️ 价格¥{price:.2f}跌破下轨¥{bb_lower:.2f},但仍属飞刀下坠")
                else:
                    insights.append(f"💎 价格¥{price:.2f}突破下轨¥{bb_lower:.2f},超卖信号强烈")
            elif price < bb_middle:
                insights.append(f"📍 价格¥{price:.2f}位于布林带下半区(位置{bb_position:.0f}%),偏向买入区域")
            elif price > bb_upper:
                insights.append(f"⚠️ 价格¥{price:.2f}突破上轨¥{bb_upper:.2f},超买风险较高")
            else:
                insights.append(f"📍 价格¥{price:.2f}位于布林带上半区(位置{bb_position:.0f}%),偏向观望")

        # MACD 洞察(增强版)
        if macd is not None and macd_signal is not None and macd_histogram is not None:
            if macd > macd_signal and macd_histogram > 0:
                if macd_histogram > 1:
                    insights.append(f"🚀 MACD金叉且柱状图{macd_histogram:.2f},上涨动能强劲")
                else:
                    insights.append(f"✅ MACD金叉,柱状图{macd_histogram:.2f},上涨趋势形成")
            elif macd < macd_signal and macd_histogram < 0:
                if abs(macd_histogram) < 0.5:
                    insights.append(f"💡 MACD死叉但柱状图收窄({macd_histogram:.2f}),下跌动能减弱,可能即将反转")
                else:
                    insights.append(f"⬇️ MACD死叉,柱状图{macd_histogram:.2f},下跌趋势延续")

            # MACD零轴判断
            if macd < 0 and macd_signal < 0:
                insights.append("📉 MACD双线位于零轴下方,中期趋势偏弱")
            elif macd > 0 and macd_signal > 0:
                insights.append("📈 MACD双线位于零轴上方,中期趋势偏强")

        # 均线洞察(增强版)
        if price and ma_medium:
            deviation = (price - ma_medium) / ma_medium * 100
            if deviation < -3:
                insights.append(f"💰 价格远低于30日均线{abs(deviation):.1f}%,严重偏离,反弹概率大")
            elif deviation < -1:
                insights.append(f"📊 价格低于30日均线{abs(deviation):.1f}%,存在回归动力")
            elif deviation > 3:
                insights.append(f"⚠️ 价格远高于30日均线{deviation:.1f}%,回调风险增加")
            elif deviation > 1:
                insights.append(f"📊 价格高于30日均线{deviation:.1f}%,短期偏强")

        # 波动率洞察
        if volatility is not None:
            if volatility < 1:
                insights.append(f"😴 波动率极低({volatility:.2f}),市场平静,可能酝酿变盘")
            elif volatility < 2:
                insights.append(f"📊 波动率较低({volatility:.2f}),市场相对平稳")
            elif volatility > 5:
                insights.append(f"⚡ 波动率较高({volatility:.2f}),市场波动剧烈,注意风险控制")

        return insights if insights else ["当前指标处于正常范围"]

    def _identify_risks(self, indicators: Dict, score: int) -> List[str]:
        """识别风险因素"""
        risks = []
        risk_flags = set(indicators.get('_risk_flags', []))
        entry_context = self._get_entry_context(indicators)

        rsi = indicators.get('rsi')
        price = indicators.get('current_price')
        ma_medium = indicators.get('ma_medium')
        ma_long = indicators.get('ma_long')
        macd = indicators.get('macd')
        macd_signal = indicators.get('macd_signal')
        volatility = indicators.get('volatility')

        if 'falling_knife' in risk_flags:
            risks.append("存在飞刀风险: 多周期下跌共振且动能未明显衰减,当前不宜贸然抄底")

        if len(entry_context.get('setup_flags', [])) >= 2 and not entry_context.get('entry_ready', False):
            risks.append("入场形态初步具备,但反转确认仍不足,更适合继续观察而非立即执行")

        # 趋势风险
        if price and ma_medium and ma_long:
            if ma_medium < ma_long:
                risks.append("中期均线低于长期均线,整体趋势偏弱")

        # 超卖反弹风险
        if score <= 40 and rsi is not None and rsi < 35:
            risks.append("虽处超卖区,但需确认是否触底,建议分批买入")

        # MACD 背离风险
        if macd is not None and macd_signal is not None:
            if macd < macd_signal and macd < 0:
                risks.append("MACD 处于零轴下方且死叉,下跌趋势可能延续")

        # 波动率风险
        if volatility is not None and volatility > 5:
            risks.append("市场波动较大,建议控制仓位,设置止损")

        # 通用风险提示
        if score <= 40:
            risks.append("建议分批买入,控制单次买入比例")

        if not risks:
            risks.append("当前风险可控,但仍需关注市场变化")

        return risks

    def _build_signal_risk_context(self, indicators: Dict) -> Dict:
        enriched = dict(indicators)
        momentum = get_price_momentum(30)
        timeframe = analyze_multi_timeframe()
        entry_context = build_entry_context(enriched, momentum, timeframe)
        risk_flags = list(entry_context["risk_flags"])

        enriched['_momentum_context'] = momentum
        enriched['_timeframe_context'] = timeframe
        enriched['_risk_flags'] = risk_flags
        enriched['_entry_context'] = entry_context
        return enriched

    def _get_entry_context(self, indicators: Dict) -> Dict:
        entry_context = indicators.get('_entry_context')
        if entry_context:
            return entry_context

        momentum = indicators.get('_momentum_context') or {}
        timeframe = indicators.get('_timeframe_context') or {}
        if momentum and timeframe:
            return build_entry_context(indicators, momentum, timeframe)

        return {
            "setup_flags": [],
            "confirmation_flags": [],
            "core_confirmation_flags": [],
            "risk_flags": indicators.get('_risk_flags', []),
            "entry_ready": False,
            "entry_weak": False,
        }

    def _format_key_indicators(self, indicators: Dict) -> Dict:
        """格式化关键指标"""
        price = indicators.get('current_price')
        rsi = indicators.get('rsi')
        macd = indicators.get('macd')
        macd_signal = indicators.get('macd_signal')

        # MACD 信号判断
        macd_status = "中性"
        if macd is not None and macd_signal is not None:
            if macd > macd_signal:
                diff = abs(macd - macd_signal)
                if diff < 0.5:
                    macd_status = "接近金叉"
                else:
                    macd_status = "金叉"
            else:
                diff = abs(macd - macd_signal)
                if diff < 0.5:
                    macd_status = "接近死叉"
                else:
                    macd_status = "死叉"

        return {
            "current_price": round(price, 2) if price else None,
            "rsi": round(rsi, 1) if rsi is not None else None,
            "macd_signal": macd_status
        }

    def _calculate_confidence(self, indicators: Dict, score: int, recommendation: str) -> float:
        entry_context = self._get_entry_context(indicators)
        risk_flags = set(indicators.get('_risk_flags', []))

        distance_score = abs(score - 50) / 50
        setup_strength = min(len(entry_context.get('setup_flags', [])) / 3, 1)
        confirmation_strength = min(len(entry_context.get('confirmation_flags', [])) / 3, 1)

        confidence = 0.35 + distance_score * 0.25 + setup_strength * 0.2 + confirmation_strength * 0.2

        if 'falling_knife' in risk_flags:
            confidence = max(confidence, 0.82)
        elif recommendation in {"强烈推荐买入", "推荐买入"} and not entry_context.get('entry_ready', False):
            confidence -= 0.15
        elif recommendation == "观望" and len(entry_context.get('setup_flags', [])) >= 2:
            confidence += 0.05

        return round(max(0.35, min(confidence, 0.97)), 2)

    def _get_dominant_factor(self, indicators: Dict, score: int, recommendation: str) -> str:
        entry_context = self._get_entry_context(indicators)
        risk_flags = set(indicators.get('_risk_flags', []))
        rsi = indicators.get('rsi')
        macd_histogram = indicators.get('macd_histogram')

        if 'falling_knife' in risk_flags:
            return "飞刀风险主导"
        if len(entry_context.get('setup_flags', [])) >= 2 and not entry_context.get('entry_ready', False):
            return "反转确认不足"
        if recommendation in {"强烈推荐买入", "推荐买入"}:
            if rsi is not None and rsi < 25:
                return "超卖反转机会"
            return "多因子偏多"
        if recommendation in {"不推荐", "强烈不推荐"}:
            if macd_histogram is not None and macd_histogram < -0.5:
                return "空头动量主导"
            return "风险因子主导"
        return "信号分歧偏中性"

    def _get_latest_price_timestamp(self) -> Optional[datetime]:
        with get_db_session(read_only=True) as session:
            latest = session.query(PriceHistory.timestamp).order_by(
                PriceHistory.timestamp.desc()
            ).first()
            return latest[0] if latest else None

    @staticmethod
    def _format_advice_label(snapshot: Dict) -> str:
        recommendation = snapshot.get("recommendation") or "未知建议"
        action_label = snapshot.get("action_label") or "未知动作"
        return f"{recommendation} / {action_label}"

    @staticmethod
    def _snapshot_state_key(snapshot: Dict) -> tuple:
        return (
            snapshot.get("recommendation"),
            snapshot.get("action_label"),
            tuple(sorted(snapshot.get("risk_flags", []))),
            snapshot.get("dominant_factor"),
        )

    @staticmethod
    def _load_json_value(raw: Optional[str], default):
        if not raw:
            return default.copy() if isinstance(default, dict) else list(default)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return default.copy() if isinstance(default, dict) else list(default)
        if isinstance(default, dict):
            return payload if isinstance(payload, dict) else {}
        return payload if isinstance(payload, list) else []

    @staticmethod
    def _risk_flag_label(flag: str) -> str:
        mapping = {
            "falling_knife": "飞刀风险",
            "trend_not_confirmed": "趋势未确认",
            "high_volatility": "高波动风险",
        }
        return mapping.get(flag, flag)

    def _persist_advice_snapshot(self, snapshot_timestamp: datetime, advice: Dict):
        risk_flags = advice.get("risk_flags", [])
        key_indicators = advice.get("key_indicators", {})
        payload = {
            "score": advice.get("score"),
            "confidence": advice.get("confidence"),
            "recommendation": advice.get("recommendation"),
            "action_label": advice.get("action_label"),
            "dominant_factor": advice.get("dominant_factor"),
            "market_state": advice.get("market_state"),
            "risk_flags": risk_flags,
            "key_indicators": key_indicators,
        }

        with get_db_session() as session:
            existing = session.query(AdviceSnapshot).filter(
                AdviceSnapshot.snapshot_timestamp == snapshot_timestamp
            ).first()

            if existing is None:
                existing = AdviceSnapshot(snapshot_timestamp=snapshot_timestamp)
                session.add(existing)

            existing.recommendation = advice.get("recommendation") or "观望"
            existing.action_label = advice.get("action_label") or "继续观望"
            existing.score = int(advice.get("score", 50))
            existing.confidence = advice.get("confidence")
            existing.dominant_factor = advice.get("dominant_factor")
            existing.risk_flags = json.dumps(risk_flags, ensure_ascii=False)
            existing.key_indicators = json.dumps(key_indicators, ensure_ascii=False)
            existing.payload = json.dumps(payload, ensure_ascii=False)

    def _list_recent_advice_snapshots(self, limit: int = 120) -> List[Dict]:
        with get_db_session(read_only=True) as session:
            snapshots = (
                session.query(
                    AdviceSnapshot.snapshot_timestamp,
                    AdviceSnapshot.recommendation,
                    AdviceSnapshot.action_label,
                    AdviceSnapshot.score,
                    AdviceSnapshot.confidence,
                    AdviceSnapshot.dominant_factor,
                    AdviceSnapshot.risk_flags,
                    AdviceSnapshot.key_indicators,
                    AdviceSnapshot.payload,
                )
                .order_by(AdviceSnapshot.snapshot_timestamp.desc())
                .limit(limit)
                .all()
            )

        items = []
        for (
            snapshot_timestamp,
            recommendation,
            action_label,
            score,
            confidence,
            dominant_factor,
            risk_flags_raw,
            key_indicators_raw,
            payload_raw,
        ) in snapshots:
            items.append(
                {
                    "snapshot_timestamp": snapshot_timestamp,
                    "recommendation": recommendation,
                    "action_label": action_label,
                    "score": score,
                    "confidence": confidence,
                    "dominant_factor": dominant_factor,
                    "risk_flags": self._load_json_value(risk_flags_raw, []),
                    "key_indicators": self._load_json_value(key_indicators_raw, {}),
                    "payload": self._load_json_value(payload_raw, {}),
                }
            )
        return items

    @staticmethod
    def _format_numeric_change(label: str, previous: float, current: float, precision: int = 1) -> str:
        delta = current - previous
        threshold = 0.1 if precision else 1
        if abs(delta) < threshold:
            return ""
        direction = "上升" if delta > 0 else "下降"
        return (
            f"{label}{direction} {abs(delta):.{precision}f}"
            f"（{previous:.{precision}f} → {current:.{precision}f}）"
        )

    @staticmethod
    def _format_percent_change(label: str, previous: float, current: float) -> str:
        delta = (current - previous) * 100
        if abs(delta) < 1:
            return ""
        direction = "上升" if delta > 0 else "下降"
        return (
            f"{label}{direction} {abs(delta):.0f} 个百分点"
            f"（{previous * 100:.0f}% → {current * 100:.0f}%）"
        )

    def _build_factor_changes(self, current: Dict, previous: Dict) -> List[str]:
        changes: List[str] = []

        previous_factor = previous.get("dominant_factor")
        current_factor = current.get("dominant_factor")
        if previous_factor and current_factor and previous_factor != current_factor:
            changes.append(f"主导因子切换：{previous_factor} → {current_factor}")

        previous_risks = set(previous.get("risk_flags", []))
        current_risks = set(current.get("risk_flags", []))
        added_risks = current_risks - previous_risks
        removed_risks = previous_risks - current_risks
        if added_risks:
            changes.append(
                "新增风险标签：" + "、".join(self._risk_flag_label(flag) for flag in sorted(added_risks))
            )
        if removed_risks:
            changes.append(
                "风险缓释：" + "、".join(self._risk_flag_label(flag) for flag in sorted(removed_risks))
            )

        score_change = self._format_numeric_change(
            "评分",
            float(previous.get("score", 0)),
            float(current.get("score", 0)),
            precision=0,
        )
        if score_change:
            changes.append(score_change.replace(".0", ""))

        previous_confidence = previous.get("confidence")
        current_confidence = current.get("confidence")
        if previous_confidence is not None and current_confidence is not None:
            confidence_change = self._format_percent_change(
                "置信度",
                float(previous_confidence),
                float(current_confidence),
            )
            if confidence_change:
                changes.append(confidence_change)

        previous_indicators = previous.get("key_indicators", {})
        current_indicators = current.get("key_indicators", {})

        rsi_prev = previous_indicators.get("rsi")
        rsi_current = current_indicators.get("rsi")
        if rsi_prev is not None and rsi_current is not None:
            rsi_change = self._format_numeric_change("RSI", float(rsi_prev), float(rsi_current), precision=1)
            if rsi_change:
                changes.append(rsi_change)

        price_prev = previous_indicators.get("current_price")
        price_current = current_indicators.get("current_price")
        if price_prev is not None and price_current is not None:
            price_delta = float(price_current) - float(price_prev)
            if abs(price_delta) >= 0.5:
                direction = "上升" if price_delta > 0 else "下降"
                changes.append(
                    f"现价{direction} ¥{abs(price_delta):.2f}"
                    f"（¥{float(price_prev):.2f} → ¥{float(price_current):.2f}）"
                )

        return changes[:4]

    def _build_explainability_timeline(self, snapshot_timestamp: datetime) -> Dict:
        snapshots = self._list_recent_advice_snapshots()
        if not snapshots:
            return {
                "previous_advice": "无历史记录",
                "changed_at": None,
                "factor_changes": ["首次建议记录，后续将显示关键因子变化。"],
                "summary": "首次生成建议，后续将追踪建议切换原因。",
            }

        current_index = next(
            (
                idx
                for idx, snapshot in enumerate(snapshots)
                if snapshot.get("snapshot_timestamp") == snapshot_timestamp
            ),
            0,
        )
        current_snapshot = snapshots[current_index]
        current_state = self._snapshot_state_key(current_snapshot)
        transition_snapshot = current_snapshot
        previous_distinct = None

        for older_snapshot in snapshots[current_index + 1:]:
            if self._snapshot_state_key(older_snapshot) == current_state:
                transition_snapshot = older_snapshot
                continue
            previous_distinct = older_snapshot
            break

        if previous_distinct is None:
            changed_at = transition_snapshot["snapshot_timestamp"].isoformat()
            return {
                "previous_advice": "无历史记录",
                "changed_at": changed_at,
                "factor_changes": ["首次建议记录，后续将显示关键因子变化。"],
                "summary": "首次生成建议，后续将追踪建议切换原因。",
            }

        factor_changes = self._build_factor_changes(transition_snapshot, previous_distinct)
        previous_advice = self._format_advice_label(previous_distinct)
        current_advice = self._format_advice_label(transition_snapshot)
        changed_at = transition_snapshot["snapshot_timestamp"].isoformat()

        if factor_changes:
            summary = (
                f"建议由{previous_advice}切换为{current_advice}，"
                f"变化发生在 {changed_at}，主因是{factor_changes[0]}。"
            )
        else:
            summary = (
                f"建议由{previous_advice}切换为{current_advice}，"
                f"变化发生在 {changed_at}。"
            )

        return {
            "previous_advice": previous_advice,
            "changed_at": changed_at,
            "factor_changes": factor_changes or ["主导建议已变化，但暂无足够因子差异可展示。"],
            "summary": summary,
        }

    def _finalize_advice_payload(self, advice: Dict, snapshot_timestamp: Optional[datetime]) -> Dict:
        effective_timestamp = snapshot_timestamp or self._get_latest_price_timestamp() or datetime.now()
        finalized = dict(advice)
        self._persist_advice_snapshot(effective_timestamp, finalized)
        explainability = self._build_explainability_timeline(effective_timestamp)
        finalized["explainability"] = explainability
        finalized["recommendation_change_reason"] = explainability["summary"]
        return finalized

    def _get_action_guidance(self, indicators: Dict, score: int, recommendation: str) -> Dict[str, str]:
        risk_flags = set(indicators.get('_risk_flags', []))
        entry_context = self._get_entry_context(indicators)

        if 'falling_knife' in risk_flags:
            return {
                "action_label": "避免抄底",
                "action_detail": "等待跌势钝化、量能收缩或重新站回关键均线后，再考虑试探性布局。",
            }

        if len(entry_context.get('setup_flags', [])) >= 2 and not entry_context.get('entry_ready', False):
            return {
                "action_label": "继续观望",
                "action_detail": "当前已有超卖迹象，但确认信号不足，先等待 MACD 或短线动量进一步修复。",
            }

        if recommendation == "强烈推荐买入":
            return {
                "action_label": "分批试探",
                "action_detail": "可考虑小仓位分批吸纳，优先等待回踩企稳，不建议一次性重仓。",
            }

        if recommendation == "推荐买入":
            return {
                "action_label": "小仓分批",
                "action_detail": "当前更适合用分批方式试探，保留后续加仓空间并设置止损。",
            }

        if recommendation == "观望":
            return {
                "action_label": "继续观望",
                "action_detail": "等待 MACD、均线或布林带出现更明确的共振信号，再决定是否进场。",
            }

        if score >= 75:
            return {
                "action_label": "控制风险",
                "action_detail": "短线不宜追价，优先等待波动回落或趋势修复后再评估。",
            }

        return {
            "action_label": "避免抄底",
            "action_detail": "当前优势并不明显，建议先观察趋势变化与风险缓释信号。",
        }

    def _build_chart_status(self) -> Dict[str, Dict[str, Optional[str]]]:
        with get_db_session(read_only=True) as session:
            now = datetime.now()
            line_rows = (
                session.query(PriceHistory.timestamp, PriceHistory.price_cny_per_gram)
                .filter(PriceHistory.timestamp >= now - timedelta(days=30))
                .order_by(PriceHistory.timestamp.asc())
                .all()
            )
            candle_rows = (
                session.query(PriceHistory.timestamp, PriceHistory.price_cny_per_gram)
                .filter(PriceHistory.timestamp >= now - timedelta(days=7))
                .order_by(PriceHistory.timestamp.asc())
                .all()
            )

        line_items = [
            {"timestamp": timestamp, "price": price}
            for timestamp, price in line_rows
        ]
        candle_items = [
            {"timestamp": timestamp, "price": price}
            for timestamp, price in candle_rows
        ]

        line_meta = build_regime_meta(
            line_items,
            price_getter=lambda item: item["price"],
            timestamp_getter=lambda item: item["timestamp"],
        )
        candle_meta = build_regime_meta(
            candle_items,
            price_getter=lambda item: item["price"],
            timestamp_getter=lambda item: item["timestamp"],
        )

        def describe(meta: Dict, label_when_ok: str, detail_when_ok: str) -> Dict[str, Optional[str]]:
            if meta["returned_points"] == 0:
                return {
                    "label": "暂无有效数据",
                    "detail": "当前没有足够的连续有效价格可用于绘图。",
                }
            if meta["regime_filtered"]:
                return {
                    "label": "已切换当前有效价格段",
                    "detail": "系统已剔除旧异常价格段，出现时间断点属于预期行为。",
                }
            return {
                "label": label_when_ok,
                "detail": detail_when_ok,
            }

        return {
            "line": describe(
                line_meta,
                "连续价格段",
                "折线图当前展示的是一段连续有效价格，没有检测到异常断层。",
            ),
            "candlestick": describe(
                candle_meta,
                "连续K线段",
                "K线图基于当前连续有效价格段聚合，当前形态可直接参与分析。",
            ),
        }

    def analyze(self, snapshot_timestamp: Optional[datetime] = None) -> Optional[Dict]:
        """综合分析并生成建议"""
        # 获取所有技术指标
        indicators = self.calculator.calculate_all()

        if indicators is None:
            return None

        indicators = self._build_signal_risk_context(indicators)
        decision_core = evaluate_decision_core(
            indicators,
            momentum=indicators.get('_momentum_context'),
            timeframe=indicators.get('_timeframe_context'),
        )
        indicators['_risk_flags'] = decision_core['risk_flags']
        indicators['_entry_context'] = decision_core['entry_context']

        # 计算评分
        score = self._calculate_score(indicators)

        # 生成建议
        recommendation = self._get_recommendation(score)
        recommendation = self._align_recommendation_with_entry_context(recommendation, indicators)

        # 生成市场状态描述
        market_state = self._describe_market_state(indicators)

        # 生成洞察
        insights = self._generate_insights(indicators)

        # 识别风险
        risks = self._identify_risks(indicators, score)

        # 格式化关键指标
        key_indicators = self._format_key_indicators(indicators)
        action_guidance = self._get_action_guidance(indicators, score, recommendation)
        confidence = self._calculate_confidence(indicators, score, recommendation)
        dominant_factor = self._get_dominant_factor(indicators, score, recommendation)
        position_payload = build_current_position_advice(
            current_price=indicators.get("current_price"),
            recommendation=recommendation,
            indicators=indicators,
        )

        advice = {
            "score": score,
            "confidence": confidence,
            "dominant_factor": dominant_factor,
            "recommendation": recommendation,
            "market_state": market_state,
            "risk_flags": indicators.get("_risk_flags", []),
            "entry_ready": decision_core["entry_ready"],
            "entry_weak": decision_core.get("entry_weak", False),
            "setup_flags": decision_core["setup_flags"],
            "confirmation_flags": decision_core["confirmation_flags"],
            "regime": decision_core["regime"],
            "upside_probability": decision_core["upside_probability"],
            "probability_horizon_days": decision_core.get("probability_horizon_days"),
            "downside_risk_bp": decision_core["downside_risk_bp"],
            "expected_return_bp": decision_core["expected_return_bp"],
            "suggested_position_pct": decision_core["suggested_position_pct"],
            "chart_status": self._build_chart_status(),
            "action_label": action_guidance["action_label"],
            "action_detail": action_guidance["action_detail"],
            "position": position_payload["position"],
            "sell_advice": position_payload["sell_advice"],
            "insights": insights,
            "risks": risks,
            "disclaimer": "本建议仅供参考,不构成投资建议,投资有风险",
            "key_indicators": key_indicators
        }
        return self._finalize_advice_payload(advice, snapshot_timestamp)

    def analyze_cached(self) -> Optional[Dict]:
        """综合分析并生成建议(带缓存)"""
        from config import settings

        with get_db_session(read_only=True) as session:
            latest = session.query(PriceHistory.timestamp).order_by(
                PriceHistory.timestamp.desc()
            ).first()

            if not latest:
                return self.analyze()

            position = get_position_state()
            position_version = position.get("updated_at") or "no-position"
            cache_key = build_cache_key(
                "analysis",
                self.CACHE_SCHEMA_VERSION,
                latest[0].isoformat(),
                position_version,
            )

        cached = get_json_cache(cache_key)
        if cached is not None:
            return self._finalize_advice_payload(cached, latest[0])

        result = self.analyze(snapshot_timestamp=latest[0])
        if result is None:
            return None

        set_json_cache(cache_key, result, settings.cache_analysis_ttl)

        return result
