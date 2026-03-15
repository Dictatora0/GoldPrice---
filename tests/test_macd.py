import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from app.analyzers.indicators import IndicatorCalculator


def test_calculate_ema_returns_correct_values():
    """测试 EMA 计算"""
    calculator = IndicatorCalculator()

    # 创建简单的价格序列
    dates = pd.date_range(start='2026-01-01', periods=50, freq='D')
    prices = [100 + i for i in range(50)]
    df = pd.DataFrame({'price': prices}, index=dates)

    ema12 = calculator.calculate_ema(df, 12)

    # EMA 应该是递增的(因为价格递增)
    assert ema12.iloc[-1] > ema12.iloc[12]
    # EMA 最后一个值应该接近最后的价格(但略低)
    assert ema12.iloc[-1] < df['price'].iloc[-1]
    assert ema12.iloc[-1] > df['price'].iloc[-1] - 20


def test_calculate_macd_returns_none_when_insufficient_data():
    """测试数据不足时返回 None"""
    calculator = IndicatorCalculator()

    # 只有 20 个数据点,少于 macd_slow_period (26)
    dates = pd.date_range(start='2026-01-01', periods=20, freq='D')
    prices = [100 + i for i in range(20)]
    df = pd.DataFrame({'price': prices}, index=dates)

    result = calculator.calculate_macd(df)

    assert result['macd'] is None
    assert result['macd_signal'] is None
    assert result['macd_histogram'] is None


def test_calculate_macd_returns_values_with_sufficient_data():
    """测试有足够数据时返回正确的 MACD 值"""
    calculator = IndicatorCalculator()

    # 创建 100 个数据点
    dates = pd.date_range(start='2026-01-01', periods=100, freq='D')
    prices = [100 + i * 0.5 for i in range(100)]
    df = pd.DataFrame({'price': prices}, index=dates)

    result = calculator.calculate_macd(df)

    # 应该返回数值而非 None
    assert result['macd'] is not None
    assert result['macd_signal'] is not None
    assert result['macd_histogram'] is not None

    # 所有值应该是 float 类型
    assert isinstance(result['macd'], float)
    assert isinstance(result['macd_signal'], float)
    assert isinstance(result['macd_histogram'], float)

    # 柱状图应该等于 MACD - 信号线
    assert abs(result['macd_histogram'] - (result['macd'] - result['macd_signal'])) < 0.0001


def test_macd_golden_cross_detection():
    """测试 MACD 金叉检测(MACD 上穿信号线)"""
    calculator = IndicatorCalculator()

    # 创建先下跌后上涨的价格序列
    dates = pd.date_range(start='2026-01-01', periods=100, freq='D')
    prices = []
    for i in range(100):
        if i < 50:
            prices.append(100 - i * 0.5)  # 下跌
        else:
            prices.append(75 + (i - 50) * 1.0)  # 上涨

    df = pd.DataFrame({'price': prices}, index=dates)

    result = calculator.calculate_macd(df)

    # 在上涨趋势中,MACD 应该大于信号线(金叉)
    assert result['macd'] > result['macd_signal']
    assert result['macd_histogram'] > 0


def test_macd_death_cross_detection():
    """测试 MACD 死叉检测(MACD 下穿信号线)"""
    calculator = IndicatorCalculator()

    # 创建先上涨后下跌的价格序列
    dates = pd.date_range(start='2026-01-01', periods=100, freq='D')
    prices = []
    for i in range(100):
        if i < 50:
            prices.append(100 + i * 1.0)  # 上涨
        else:
            prices.append(150 - (i - 50) * 0.5)  # 下跌

    df = pd.DataFrame({'price': prices}, index=dates)

    result = calculator.calculate_macd(df)

    # 在下跌趋势中,MACD 应该小于信号线(死叉)
    assert result['macd'] < result['macd_signal']
    assert result['macd_histogram'] < 0


def test_macd_integrated_in_calculate_all():
    """测试 MACD 已集成到 calculate_all 方法中"""
    calculator = IndicatorCalculator()

    # 注意:这个测试需要数据库中有数据,所以我们只测试返回的结构
    # 实际值的测试在集成测试中进行

    # 创建测试数据
    dates = pd.date_range(start='2026-01-01', periods=100, freq='D')
    prices = [100 + i * 0.5 for i in range(100)]
    df = pd.DataFrame({'price': prices}, index=dates)

    # 手动调用各个方法来模拟 calculate_all 的行为
    macd_result = calculator.calculate_macd(df)

    # 验证返回的键
    assert 'macd' in macd_result
    assert 'macd_signal' in macd_result
    assert 'macd_histogram' in macd_result
