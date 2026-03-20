import json
import shutil
import subprocess
import textwrap
from datetime import datetime, timedelta
from pathlib import Path

import pytest


CHART_JS = Path(__file__).resolve().parents[1] / "static" / "js" / "chart.js"


def run_chart_function(function_name: str, items, interval: str):
    if not shutil.which("node"):
        pytest.skip("node is required to execute frontend chart helpers")

    script = textwrap.dedent(
        f"""
        const fs = require("fs");
        const vm = require("vm");
        const code = fs.readFileSync({json.dumps(str(CHART_JS))}, "utf8");
        const context = {{
          console,
          AbortController,
          setTimeout,
          clearTimeout,
          fetch: async () => ({{ ok: false, json: async () => ({{}}) }}),
          Chart: function Chart() {{}},
          window: {{
            setTimeout,
            clearTimeout,
            setInterval: () => 0,
            clearInterval: () => {{}},
            requestAnimationFrame: (callback) => callback(),
          }},
          document: {{
            readyState: "loading",
            hidden: true,
            addEventListener: () => {{}},
            getElementById: () => null,
          }},
        }};
        context.window.document = context.document;
        vm.createContext(context);
        vm.runInContext(code, context);
        const result = context[{json.dumps(function_name)}](
          {json.dumps(items, ensure_ascii=False)},
          {json.dumps(interval)}
        );
        process.stdout.write(JSON.stringify(result));
        """
    )

    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_build_line_chart_context_interprets_trend_and_position():
    base = datetime(2026, 3, 20, 0, 0, 0)
    items = []
    for index in range(36):
        price = 705 + index * 0.9
        if index >= 30:
            price += (index - 29) * 0.45
        items.append(
            {
                "timestamp": (base + timedelta(hours=index)).isoformat(),
                "price_cny_per_gram": round(price, 2),
            }
        )

    result = run_chart_function("buildLineChartContext", items, "1h")

    assert "上行" in result["state"]
    assert "高位" in result["state"]
    assert "MA30" in result["detail"]
    assert "上方" in result["detail"]
    assert "区间" in result["detail"]


def test_build_candlestick_chart_context_interprets_wicks_and_participation():
    base = datetime(2026, 3, 20, 0, 0, 0)
    items = [
        {
            "timestamp": (base + timedelta(hours=offset)).isoformat(),
            "open": candle["open"],
            "high": candle["high"],
            "low": candle["low"],
            "close": candle["close"],
            "activity": candle["activity"],
            "data_points": candle["data_points"],
        }
        for offset, candle in enumerate(
            [
                {"open": 720.0, "high": 721.2, "low": 717.8, "close": 718.4, "activity": 3.2, "data_points": 8},
                {"open": 718.4, "high": 719.0, "low": 715.7, "close": 716.1, "activity": 3.5, "data_points": 9},
                {"open": 716.1, "high": 717.4, "low": 713.6, "close": 714.2, "activity": 4.1, "data_points": 10},
                {"open": 714.2, "high": 715.1, "low": 710.9, "close": 712.0, "activity": 4.5, "data_points": 11},
                {"open": 712.0, "high": 713.0, "low": 708.6, "close": 709.5, "activity": 5.0, "data_points": 12},
                {"open": 709.4, "high": 715.3, "low": 704.2, "close": 714.6, "activity": 16.8, "data_points": 26},
            ]
        )
    ]

    result = run_chart_function("buildCandlestickChartContext", items, "1h")

    assert "下探回收" in result["state"]
    assert "活跃度高" in result["state"]
    assert "下影" in result["detail"]
    assert "承接" in result["detail"]
    assert "活跃度" in result["detail"]
