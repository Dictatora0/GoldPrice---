from app.collectors.sina import SinaCollector
from app.collectors.eastmoney import EastMoneyCollector
from app.collectors.gold_cn import GoldCNCollector


def test_sina_parse_price():
    text = 'var hq_str_hf_AUTD="黄金T+D,644.52,644.54,644.50,644.61,644.49,";'
    assert SinaCollector.parse_price(text) == 644.52


def test_eastmoney_extract_price():
    payload = {
        "data": {
            "diff": [
                {"f12": "AU9999", "f14": "黄金9999", "f2": 1121.0},
                {"f12": "AUTD", "f14": "黄金T+D", "f2": 1124.86},
            ]
        }
    }

    assert EastMoneyCollector.extract_price(payload, code="AU9999") == 1121.0


def test_sge_extract_price():
    html = """
    <table>
      <thead>
        <tr><th>合约</th><th>最新价</th><th>涨跌</th></tr>
      </thead>
      <tbody>
        <tr><td>Au99.99</td><td>1118.90</td><td>-0.75</td></tr>
        <tr><td>Au(T+D)</td><td>1124.86</td><td>-0.58</td></tr>
      </tbody>
    </table>
    """

    assert GoldCNCollector.extract_price(html, symbol="Au99.99") == 1118.90
