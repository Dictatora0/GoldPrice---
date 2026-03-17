from typing import Dict, List, Optional
from datetime import datetime, timedelta
from app.analyzers.indicators import IndicatorCalculator
from app.database import get_db_session
from app.models import PriceHistory


class MarketAdvisor:
    """市场智能顾问 - 基于多指标综合分析提供买入建议(增强版)"""

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
        with get_db_session() as session:
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
        score = 50  # 基准分

        # 提取指标值
        rsi = indicators.get('rsi')
        price = indicators.get('current_price')
        bb_lower = indicators.get('bb_lower')
        bb_middle = indicators.get('bb_middle')
        bb_upper = indicators.get('bb_upper')
        ma_medium = indicators.get('ma_medium')
        macd = indicators.get('macd')
        macd_signal = indicators.get('macd_signal')
        macd_histogram = indicators.get('macd_histogram')

        # RSI 评分 (权重 30%)
        if rsi is not None:
            if rsi < 30:
                score -= 15  # 超卖,强烈买入信号
            elif rsi < 40:
                score -= 10  # 接近超卖
            elif rsi > 70:
                score += 15  # 超买,不推荐
            elif rsi > 60:
                score += 10  # 接近超买

        # 布林带位置 (权重 25%)
        if price and bb_lower and bb_middle and bb_upper:
            if price < bb_lower:
                score -= 12  # 价格低于下轨,超卖
            elif price < bb_middle:
                score -= 6   # 价格在下轨和中轨之间
            elif price > bb_upper:
                score += 12  # 价格高于上轨,超买
            elif price > bb_middle:
                score += 6   # 价格在中轨和上轨之间

        # MACD (权重 25%)
        if macd is not None and macd_signal is not None and macd_histogram is not None:
            if macd > macd_signal and macd_histogram > 0:
                score += 12  # 金叉,上涨动量
            elif macd < macd_signal and macd_histogram < 0:
                score -= 12  # 死叉,下跌动量

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

    def _describe_market_state(self, indicators: Dict) -> str:
        """描述市场状态"""
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

        return "，".join(states) if states else "市场状态正常"

    def _generate_insights(self, indicators: Dict) -> List[str]:
        """生成关键洞察(增强版)"""
        insights = []

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

        rsi = indicators.get('rsi')
        price = indicators.get('current_price')
        ma_medium = indicators.get('ma_medium')
        ma_long = indicators.get('ma_long')
        macd = indicators.get('macd')
        macd_signal = indicators.get('macd_signal')
        volatility = indicators.get('volatility')

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

    def analyze(self) -> Optional[Dict]:
        """综合分析并生成建议"""
        # 获取所有技术指标
        indicators = self.calculator.calculate_all()

        if indicators is None:
            return None

        # 计算评分
        score = self._calculate_score(indicators)

        # 生成建议
        recommendation = self._get_recommendation(score)

        # 生成市场状态描述
        market_state = self._describe_market_state(indicators)

        # 生成洞察
        insights = self._generate_insights(indicators)

        # 识别风险
        risks = self._identify_risks(indicators, score)

        # 格式化关键指标
        key_indicators = self._format_key_indicators(indicators)

        return {
            "score": score,
            "recommendation": recommendation,
            "market_state": market_state,
            "insights": insights,
            "risks": risks,
            "disclaimer": "本建议仅供参考,不构成投资建议,投资有风险",
            "key_indicators": key_indicators
        }
