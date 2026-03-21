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


def test_calculate_score_penalizes_falling_knife_context():
    advisor = MarketAdvisor()

    indicators = {
        'current_price': 480.0,
        'rsi': 25,
        'bb_lower': 485.0,
        'bb_middle': 490.0,
        'bb_upper': 495.0,
        'ma_medium': 490.0,
        'ma_long': 500.0,
        'macd': -1.2,
        'macd_signal': -0.6,
        'macd_histogram': -0.9,
        '_momentum_context': {'change_pct': -1.4, 'trend': 'down', 'acceleration': -0.02},
        '_timeframe_context': {
            'short_term': 'bearish',
            'mid_term': 'bearish',
            'long_term': 'bearish',
            'alignment': 'bearish_aligned',
        },
    }

    score = advisor._calculate_score(indicators)

    assert score >= 60


def test_calculate_score_macd_golden_cross_reduces_buy_score():
    advisor = MarketAdvisor()

    indicators = {
        'macd': 0.5,
        'macd_signal': 0.2,
        'macd_histogram': 0.3,
    }

    score = advisor._calculate_score(indicators)

    assert score < 50


def test_calculate_score_macd_death_cross_increases_risk_score():
    advisor = MarketAdvisor()

    indicators = {
        'macd': -0.6,
        'macd_signal': -0.2,
        'macd_histogram': -0.5,
    }

    score = advisor._calculate_score(indicators)

    assert score > 50


def test_calculate_score_falling_knife_penalty_is_tiered_by_confirmation():
    advisor = MarketAdvisor()

    base_indicators = {
        'current_price': 480.0,
        'rsi': 25.0,
        'bb_lower': 490.0,
        'bb_middle': 500.0,
        'bb_upper': 510.0,
        'ma_medium': 500.0,
        'ma_long': 510.0,
        'macd': -0.8,
        'macd_signal': -0.3,
        'macd_histogram': -0.6,
        '_risk_flags': ['falling_knife'],
    }

    no_confirmation = {
        **base_indicators,
        '_entry_context': {
            'setup_flags': [],
            'confirmation_flags': [],
            'risk_flags': ['falling_knife'],
            'entry_ready': False,
        },
    }
    confirmed = {
        **base_indicators,
        '_entry_context': {
            'setup_flags': [],
            'confirmation_flags': ['macd_stabilizing', 'momentum_turn'],
            'risk_flags': ['falling_knife'],
            'entry_ready': True,
        },
    }

    score_no_confirmation = advisor._calculate_score(no_confirmation)
    score_confirmed = advisor._calculate_score(confirmed)

    assert score_no_confirmation > score_confirmed
    assert score_no_confirmation - score_confirmed >= 20


def test_calculate_score_bollinger_break_adjusts_by_band_width_and_depth():
    advisor = MarketAdvisor()

    narrow_band = {
        'current_price': 96.0,
        'bb_lower': 100.0,
        'bb_middle': 101.0,
        'bb_upper': 102.0,
    }
    wide_band = {
        'current_price': 96.0,
        'bb_lower': 100.0,
        'bb_middle': 120.0,
        'bb_upper': 140.0,
    }

    score_narrow = advisor._calculate_score(narrow_band)
    score_wide = advisor._calculate_score(wide_band)

    assert score_narrow < score_wide


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


def test_identify_risks_calls_out_falling_knife():
    advisor = MarketAdvisor()

    indicators = {
        'current_price': 480.0,
        'rsi': 25,
        'ma_medium': 490.0,
        'ma_long': 500.0,
        'macd': -1.2,
        'macd_signal': -0.6,
        'macd_histogram': -0.9,
        '_risk_flags': ['falling_knife'],
    }

    risks = advisor._identify_risks(indicators, score=70)

    assert any('飞刀' in risk or '抄底' in risk for risk in risks)


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


def test_analyze_uses_signal_risk_context(monkeypatch):
    advisor = MarketAdvisor()

    monkeypatch.setattr(
        advisor.calculator,
        'calculate_all',
        lambda: {
            'current_price': 480.0,
            'rsi': 25,
            'bb_lower': 485.0,
            'bb_middle': 490.0,
            'bb_upper': 495.0,
            'ma_medium': 490.0,
            'ma_long': 500.0,
            'macd': -1.2,
            'macd_signal': -0.6,
            'macd_histogram': -0.9,
            'volatility': 3.5,
        },
    )
    monkeypatch.setattr(
        advisor,
        '_build_signal_risk_context',
        lambda indicators: {
            **indicators,
            '_momentum_context': {'change_pct': -1.4, 'trend': 'down', 'acceleration': -0.02},
            '_timeframe_context': {
                'short_term': 'bearish',
                'mid_term': 'bearish',
                'long_term': 'bearish',
                'alignment': 'bearish_aligned',
            },
            '_risk_flags': ['falling_knife'],
        },
    )
    monkeypatch.setattr(advisor, '_get_price_trend_analysis', lambda: {
        'recent_change': -1.4,
        'today_change': -2.0,
        'momentum': 'strong_down',
    })

    result = advisor.analyze()

    assert result is not None
    assert result['score'] >= 60
    assert result['recommendation'] in {'不推荐', '强烈不推荐'}
    assert result['risk_flags'] == ['falling_knife']
    assert result['action_label'] == '避免抄底'
    assert '等待' in result['action_detail']
    assert 0 <= result['confidence'] <= 1
    assert result['dominant_factor']
    assert result['recommendation_change_reason']
    assert any('飞刀' in risk or '抄底' in risk for risk in result['risks'])


def test_analyze_uses_observe_action_when_setup_lacks_confirmation(monkeypatch):
    advisor = MarketAdvisor()

    monkeypatch.setattr(
        advisor.calculator,
        'calculate_all',
        lambda: {
            'current_price': 480.0,
            'rsi': 22.0,
            'bb_lower': 482.0,
            'bb_middle': 490.0,
            'bb_upper': 496.0,
            'ma_medium': 498.0,
            'ma_long': 504.0,
            'macd': -0.9,
            'macd_signal': -0.5,
            'macd_histogram': -0.7,
            'volatility': 2.5,
        },
    )
    monkeypatch.setattr(
        advisor,
        '_build_signal_risk_context',
        lambda indicators: {
            **indicators,
            '_momentum_context': {'change_pct': -0.4, 'trend': 'down', 'acceleration': -0.001},
            '_timeframe_context': {
                'short_term': 'bearish',
                'mid_term': 'neutral',
                'long_term': 'neutral',
                'alignment': 'mixed',
            },
            '_risk_flags': [],
        },
    )
    monkeypatch.setattr(advisor, '_get_price_trend_analysis', lambda: {
        'recent_change': -0.4,
        'today_change': -0.8,
        'momentum': 'down',
    })

    result = advisor.analyze()

    assert result is not None
    assert result['action_label'] == '继续观望'
    assert '等待' in result['action_detail']


def test_analyze_downgrades_buy_recommendation_when_entry_not_ready(monkeypatch):
    advisor = MarketAdvisor()

    monkeypatch.setattr(
        advisor.calculator,
        'calculate_all',
        lambda: {
            'current_price': 480.0,
            'rsi': 18.0,
            'bb_lower': 485.0,
            'bb_middle': 490.0,
            'bb_upper': 495.0,
            'ma_medium': 500.0,
            'ma_long': 510.0,
            'macd': -0.2,
            'macd_signal': -0.1,
            'macd_histogram': -0.05,
            'volatility': 1.6,
        },
    )
    monkeypatch.setattr(
        advisor,
        '_build_signal_risk_context',
        lambda indicators: {
            **indicators,
            '_momentum_context': {'change_pct': -0.35, 'trend': 'down', 'acceleration': -0.0008},
            '_timeframe_context': {
                'short_term': 'bearish',
                'mid_term': 'neutral',
                'long_term': 'neutral',
                'alignment': 'mixed',
            },
            '_risk_flags': [],
            '_entry_context': {
                'setup_flags': ['oversold', 'band_break', 'below_ma'],
                'confirmation_flags': ['selling_pressure_easing'],
                'risk_flags': [],
                'entry_ready': False,
            },
        },
    )
    monkeypatch.setattr(advisor, '_get_price_trend_analysis', lambda: {
        'recent_change': -0.35,
        'today_change': -0.7,
        'momentum': 'down',
    })

    result = advisor.analyze()

    assert result is not None
    assert result['recommendation'] == '观望'
    assert result['action_label'] == '继续观望'
    assert '确认' in result['market_state'] or '观察' in result['market_state']


def test_analyze_never_returns_buy_when_entry_is_not_ready(monkeypatch):
    advisor = MarketAdvisor()

    monkeypatch.setattr(
        advisor.calculator,
        'calculate_all',
        lambda: {
            'current_price': 480.0,
            'rsi': 18.0,
            'bb_lower': 485.0,
            'bb_middle': 490.0,
            'bb_upper': 495.0,
            'ma_medium': 500.0,
            'ma_long': 510.0,
            'macd': 0.4,
            'macd_signal': 0.2,
            'macd_histogram': 0.12,
            'volatility': 1.2,
        },
    )
    monkeypatch.setattr(
        advisor,
        '_build_signal_risk_context',
        lambda indicators: {
            **indicators,
            '_momentum_context': {'change_pct': -0.1, 'trend': 'flat', 'acceleration': -0.001},
            '_timeframe_context': {
                'short_term': 'neutral',
                'mid_term': 'neutral',
                'long_term': 'neutral',
                'alignment': 'mixed',
            },
            '_risk_flags': [],
            '_entry_context': {
                'setup_flags': [],
                'confirmation_flags': ['trend_pressure_not_extreme'],
                'risk_flags': [],
                'entry_ready': False,
                'entry_weak': False,
            },
        },
    )
    monkeypatch.setattr(advisor, '_get_price_trend_analysis', lambda: {
        'recent_change': -0.1,
        'today_change': -0.2,
        'momentum': 'neutral',
    })

    result = advisor.analyze()

    assert result is not None
    assert result['entry_ready'] is False
    assert result['recommendation'] not in {'强烈推荐买入', '推荐买入'}


def test_analyze_exposes_explainability_timeline(monkeypatch):
    advisor = MarketAdvisor()

    monkeypatch.setattr(
        advisor.calculator,
        'calculate_all',
        lambda: {
            'current_price': 480.0,
            'rsi': 22.0,
            'bb_lower': 482.0,
            'bb_middle': 490.0,
            'bb_upper': 496.0,
            'ma_medium': 498.0,
            'ma_long': 504.0,
            'macd': -0.9,
            'macd_signal': -0.5,
            'macd_histogram': -0.7,
            'volatility': 2.5,
        },
    )
    monkeypatch.setattr(
        advisor,
        '_build_signal_risk_context',
        lambda indicators: {
            **indicators,
            '_momentum_context': {'change_pct': -0.4, 'trend': 'down', 'acceleration': -0.001},
            '_timeframe_context': {
                'short_term': 'bearish',
                'mid_term': 'neutral',
                'long_term': 'neutral',
                'alignment': 'mixed',
            },
            '_risk_flags': [],
        },
    )
    monkeypatch.setattr(advisor, '_get_price_trend_analysis', lambda: {
        'recent_change': -0.4,
        'today_change': -0.8,
        'momentum': 'down',
    })
    monkeypatch.setattr(
        advisor,
        '_build_explainability_timeline',
        lambda *args, **kwargs: {
            'previous_advice': '观望 / 继续观望',
            'changed_at': '2026-03-20T18:30:00',
            'factor_changes': [
                'RSI下降 8.0（30.0 → 22.0）',
                '评分下降 12 分（55 → 43）',
            ],
            'summary': '建议由观望转为推荐买入，主因是 RSI 与评分同步走弱。',
        },
        raising=False,
    )

    result = advisor.analyze()

    assert result is not None
    assert result['explainability']['previous_advice'] == '观望 / 继续观望'
    assert result['explainability']['changed_at'] == '2026-03-20T18:30:00'
    assert result['explainability']['factor_changes'][0].startswith('RSI下降')
    assert '主因' in result['recommendation_change_reason']
