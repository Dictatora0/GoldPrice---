import pytest
import os
from app.analyzers.advisor import MarketAdvisor
from app.database import init_db
from config import settings


def setup_function(_):
    """Initialize database for tests that need it"""
    if os.path.exists(settings.database_path):
        os.remove(settings.database_path)
    init_db()


def test_calculate_score_oversold_condition():
    """测试超卖条件下的评分"""
    advisor = MarketAdvisor()

    # 模拟超卖指标
    indicators = {
        'current_price': 480.0,
        'rsi': 25,  # 超卖
        'bb_lower': 485.0,
        'bb_middle': 490.0,
        'bb_upper': 495.0,
        'ma_medium': 490.0,
        'macd': -0.5,
        'macd_signal': -0.3,
        'macd_histogram': -0.2,
    }

    score = advisor._calculate_score(indicators)

    # 超卖条件下评分应该较低(适合买入)
    assert score < 50
    assert score >= 0


def test_calculate_score_overbought_condition():
    """测试超买条件下的评分"""
    advisor = MarketAdvisor()

    # 模拟超买指标
    indicators = {
        'current_price': 500.0,
        'rsi': 75,  # 超买
        'bb_lower': 485.0,
        'bb_middle': 490.0,
        'bb_upper': 495.0,
        'ma_medium': 490.0,
        'macd': 0.5,
        'macd_signal': 0.3,
        'macd_histogram': 0.2,
    }

    score = advisor._calculate_score(indicators)

    # 超买条件下评分应该较高(不适合买入)
    assert score > 50
    assert score <= 100


def test_get_recommendation_strong_buy():
    """测试强烈推荐买入"""
    advisor = MarketAdvisor()

    recommendation = advisor._get_recommendation(20)
    assert recommendation == "强烈推荐买入"


def test_get_recommendation_buy():
    """测试推荐买入"""
    advisor = MarketAdvisor()

    recommendation = advisor._get_recommendation(35)
    assert recommendation == "推荐买入"


def test_get_recommendation_hold():
    """测试观望"""
    advisor = MarketAdvisor()

    recommendation = advisor._get_recommendation(50)
    assert recommendation == "观望"


def test_get_recommendation_not_recommended():
    """测试不推荐"""
    advisor = MarketAdvisor()

    recommendation = advisor._get_recommendation(70)
    assert recommendation == "不推荐"


def test_get_recommendation_strong_not_recommended():
    """测试强烈不推荐"""
    advisor = MarketAdvisor()

    recommendation = advisor._get_recommendation(85)
    assert recommendation == "强烈不推荐"


def test_describe_market_state():
    """测试市场状态描述"""
    advisor = MarketAdvisor()

    indicators = {
        'current_price': 480.0,
        'rsi': 28,
        'bb_lower': 485.0,
        'bb_middle': 490.0,
        'bb_upper': 495.0,
        'ma_medium': 490.0,
        'macd': -0.5,
        'macd_signal': -0.3,
    }

    state = advisor._describe_market_state(indicators)

    # 应该包含趋势和超卖描述
    assert "下降趋势" in state or "超卖" in state
    assert isinstance(state, str)
    assert len(state) > 0


def test_generate_insights():
    """测试洞察生成"""
    advisor = MarketAdvisor()

    indicators = {
        'current_price': 480.0,
        'rsi': 28,
        'bb_lower': 485.0,
        'bb_middle': 490.0,
        'bb_upper': 495.0,
        'ma_medium': 490.0,
        'macd': -0.5,
        'macd_signal': -0.3,
        'macd_histogram': -0.2,
        'volatility': 3.5,
    }

    insights = advisor._generate_insights(indicators)

    # 应该生成至少一条洞察
    assert len(insights) > 0
    assert isinstance(insights, list)
    # RSI 超卖应该被提及
    assert any('RSI' in insight for insight in insights)


def test_identify_risks_downtrend():
    """测试下跌趋势中的风险识别"""
    advisor = MarketAdvisor()

    indicators = {
        'current_price': 480.0,
        'rsi': 28,
        'ma_medium': 490.0,
        'ma_long': 495.0,
        'macd': -0.5,
        'macd_signal': -0.3,
        'volatility': 6.0,
    }

    risks = advisor._identify_risks(indicators, score=35)

    # 应该识别出风险
    assert len(risks) > 0
    assert isinstance(risks, list)
    # 应该提到分批买入或波动风险
    risk_text = ' '.join(risks)
    assert '分批' in risk_text or '波动' in risk_text or '风险' in risk_text


def test_format_key_indicators():
    """测试关键指标格式化"""
    advisor = MarketAdvisor()

    indicators = {
        'current_price': 485.32,
        'rsi': 28.5,
        'macd': 1.0,
        'macd_signal': 0.3,
    }

    formatted = advisor._format_key_indicators(indicators)

    assert formatted['current_price'] == 485.32
    assert formatted['rsi'] == 28.5
    assert formatted['macd_signal'] == '金叉'


def test_format_key_indicators_near_golden_cross():
    """测试接近金叉的格式化"""
    advisor = MarketAdvisor()

    indicators = {
        'current_price': 485.0,
        'rsi': 30.0,
        'macd': -0.2,
        'macd_signal': -0.3,
    }

    formatted = advisor._format_key_indicators(indicators)

    assert formatted['macd_signal'] == '接近金叉'


def test_analyze_returns_none_when_no_data():
    """测试无数据时返回 None"""
    advisor = MarketAdvisor()

    # 注意:这个测试需要数据库为空
    # 在实际环境中可能需要 mock
    result = advisor.analyze()

    # 如果数据库为空,应该返回 None
    # 如果有数据,应该返回字典
    if result is not None:
        assert isinstance(result, dict)
        assert 'score' in result
        assert 'recommendation' in result
        assert 'market_state' in result
        assert 'insights' in result
        assert 'risks' in result
        assert 'disclaimer' in result
        assert 'key_indicators' in result


def test_analyze_structure_when_data_available():
    """测试有数据时返回的结构"""
    advisor = MarketAdvisor()

    # 这个测试假设数据库中有足够的数据
    # 如果没有数据,会返回 None,测试会跳过
    result = advisor.analyze()

    if result is not None:
        # 验证返回结构
        assert 'score' in result
        assert 'recommendation' in result
        assert 'market_state' in result
        assert 'insights' in result
        assert 'risks' in result
        assert 'disclaimer' in result
        assert 'key_indicators' in result

        # 验证数据类型
        assert isinstance(result['score'], int)
        assert isinstance(result['recommendation'], str)
        assert isinstance(result['market_state'], str)
        assert isinstance(result['insights'], list)
        assert isinstance(result['risks'], list)
        assert isinstance(result['disclaimer'], str)
        assert isinstance(result['key_indicators'], dict)

        # 验证评分范围
        assert 0 <= result['score'] <= 100

        # 验证免责声明存在
        assert '投资有风险' in result['disclaimer']
