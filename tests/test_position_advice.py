from app.analyzers.position import build_position_advice


def test_position_advice_recommends_reduce_when_profit_and_overheated():
    advice = build_position_advice(
        current_price=630.0,
        avg_cost_price=580.0,
        quantity_gram=20.0,
        recommendation="观望",
        indicators={"rsi": 76.0, "bb_upper": 625.0, "current_price": 630.0},
    )

    assert advice["has_position"] is True
    assert advice["unrealized_pnl_pct"] == 8.621
    assert advice["action"] == "reduce"
    assert advice["action_label"] == "分批减仓"
    assert advice["suggested_sell_pct"] >= 25
    assert "RSI" in advice["reason"]


def test_position_advice_recommends_hold_without_position():
    advice = build_position_advice(
        current_price=600.0,
        avg_cost_price=None,
        quantity_gram=0,
        recommendation="推荐买入",
        indicators={"rsi": 35.0},
    )

    assert advice["has_position"] is False
    assert advice["action"] == "no_position"
    assert advice["action_label"] == "无持仓"
    assert advice["suggested_sell_pct"] == 0
