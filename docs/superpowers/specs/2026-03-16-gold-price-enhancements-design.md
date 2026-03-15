# 黄金价格监控系统增强设计文档

**日期:** 2026-03-16
**项目:** GoldPrice - 系统功能增强
**基于:** 2026-03-13-gold-price-monitor-design.md

## 1. 增强概述

本次增强将在现有黄金价格监控系统基础上添加以下功能:

1. **修复测试问题** - 修复 `test_price_history_downsample_interval` 失败
2. **MACD 指标** - 添加趋势跟踪动量指标
3. **智能解读引擎** - 基于多指标提供买入建议和风险分析
4. **WebSocket 实时推送** - 实时更新价格和指标
5. **K线图和成交量图** - 更专业的图表展示

## 2. 测试问题修复

### 2.1 问题分析

测试 `test_price_history_downsample_interval` 失败原因:
- 测试使用固定日期 `2026-03-13 10:00:00`
- API 查询使用 `datetime.now() - timedelta(days=1)`
- 时间范围不匹配导致查询结果为空

### 2.2 解决方案

修改 `app/api/price.py` 的 `downsample_history` 函数:
- 确保正确处理时间戳边界
- 修复 pandas resample 的时区问题
- 添加更健壮的空数据处理

## 3. MACD 指标

### 3.1 技术原理

**MACD (Moving Average Convergence Divergence)** 由三部分组成:

1. **MACD 线:** 快速EMA(12) - 慢速EMA(26)
2. **信号线:** MACD 的 9 日 EMA
3. **柱状图:** MACD - 信号线

**交易信号:**
- MACD 上穿信号线 → 金叉(买入信号)
- MACD 下穿信号线 → 死叉(卖出信号)
- 柱状图由负转正 → 动量增强
- 柱状图由正转负 → 动量减弱

### 3.2 实现设计

**后端实现:**

文件: `app/analyzers/indicators.py`

```python
def calculate_ema(self, df: pd.DataFrame, period: int) -> pd.Series:
    """计算指数移动平均线"""
    return df['price'].ewm(span=period, adjust=False).mean()

def calculate_macd(self, df: pd.DataFrame) -> Dict[str, float]:
    """计算 MACD 指标"""
    if len(df) < 26:
        return {}

    ema12 = self.calculate_ema(df, 12)
    ema26 = self.calculate_ema(df, 26)
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line

    return {
        "macd": macd_line.iloc[-1],
        "macd_signal": signal_line.iloc[-1],
        "macd_histogram": histogram.iloc[-1],
    }
```

**API 端点:**

现有的 `GET /api/analysis/indicators` 将自动包含 MACD 数据。

**前端展示:**

在主图表下方添加 MACD 子图:
- MACD 线(蓝色)
- 信号线(橙色)
- 柱状图(绿色/红色)

### 3.3 配置参数

添加到 `config.py`:

```python
# MACD 配置
macd_fast: int = 12
macd_slow: int = 26
macd_signal: int = 9
```

## 4. 智能解读引擎

### 4.1 分析维度

智能顾问将综合以下指标进行分析:

**1. 趋势判断**
- MA 排列: MA7 > MA30 > MA90 → 上升趋势
- MACD: MACD > 0 且柱状图增长 → 上升动量
- 价格位置: 相对布林带的位置

**2. 超买超卖**
- RSI < 30 → 超卖(买入机会)
- RSI > 70 → 超买(谨慎)
- 价格 < 布林下轨 → 超卖

**3. 动量分析**
- MACD 金叉/死叉
- 柱状图变化趋势
- 波动率变化

**4. 综合评分**
- 0-100 分,越低越适合买入
- 各指标加权计算

### 4.2 评分算法

```python
score = 50  # 基准分

# RSI 评分 (权重 30%)
if rsi < 30:
    score -= 15
elif rsi < 40:
    score -= 10
elif rsi > 70:
    score += 15
elif rsi > 60:
    score += 10

# 布林带位置 (权重 25%)
if price < bb_lower:
    score -= 12
elif price < bb_middle:
    score -= 6
elif price > bb_upper:
    score += 12

# MACD (权重 25%)
if macd > signal and histogram > 0:
    score += 12  # 金叉
elif macd < signal and histogram < 0:
    score -= 12  # 死叉

# MA 趋势 (权重 20%)
if price < ma_medium * 0.98:
    score -= 10
elif price > ma_medium * 1.02:
    score += 10
```

### 4.3 建议生成

根据评分生成建议:

- **0-25 分:** 强烈推荐买入
- **26-40 分:** 推荐买入
- **41-60 分:** 观望
- **61-75 分:** 不推荐
- **76-100 分:** 强烈不推荐

### 4.4 实现设计

**新建文件:** `app/analyzers/advisor.py`

```python
class MarketAdvisor:
    """市场智能顾问"""

    def analyze(self, indicators: Dict) -> Dict:
        """综合分析并生成建议"""
        score = self._calculate_score(indicators)
        recommendation = self._get_recommendation(score)
        insights = self._generate_insights(indicators)
        risks = self._identify_risks(indicators)

        return {
            "score": score,
            "recommendation": recommendation,
            "market_state": self._describe_market_state(indicators),
            "insights": insights,
            "risks": risks,
            "key_indicators": self._format_key_indicators(indicators)
        }
```

**API 端点:**

新增 `GET /api/analysis/advice`

返回格式:
```json
{
  "score": 32,
  "recommendation": "推荐买入",
  "market_state": "价格处于下降趋势,接近超卖区",
  "insights": [
    "RSI 为 28,处于超卖区域",
    "价格低于布林带下轨,可能反弹",
    "MACD 柱状图开始收窄,下跌动能减弱"
  ],
  "risks": [
    "整体趋势仍为下降,需关注是否继续下跌",
    "建议分批买入,控制仓位"
  ],
  "key_indicators": {
    "current_price": 485.32,
    "rsi": 28,
    "macd_signal": "接近金叉"
  }
}
```

## 5. WebSocket 实时推送

### 5.1 推送机制

**推送时机:**
- 每次数据采集完成后(3分钟一次)
- 技术指标更新后
- 买入信号触发时

**推送内容:**
```json
{
  "type": "price_update",
  "data": {
    "timestamp": "2026-03-16T10:30:00",
    "price_cny_per_gram": 485.32,
    "change_24h": -1.2
  }
}

{
  "type": "indicators_update",
  "data": {
    "rsi": 28,
    "macd": -0.5,
    "macd_signal": -0.3
  }
}

{
  "type": "signal_alert",
  "data": {
    "signal_type": "buy",
    "price": 485.32,
    "reason": "RSI超卖且MACD金叉"
  }
}
```

### 5.2 实现设计

**后端实现:**

新建文件: `app/api/websocket.py`

```python
from fastapi import WebSocket, WebSocketDisconnect
from typing import List

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
```

**调度器集成:**

修改 `app/scheduler.py`,在数据采集后广播更新:

```python
async def broadcast_update(price_data, indicators):
    await manager.broadcast({
        "type": "price_update",
        "data": price_data
    })
    await manager.broadcast({
        "type": "indicators_update",
        "data": indicators
    })
```

**前端实现:**

新建文件: `static/js/websocket.js`

```javascript
class PriceWebSocket {
  constructor(url) {
    this.url = url;
    this.ws = null;
    this.reconnectDelay = 3000;
    this.connect();
  }

  connect() {
    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      console.log('WebSocket connected');
      document.getElementById('status-pill').textContent = '在线';
    };

    this.ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      this.handleMessage(message);
    };

    this.ws.onclose = () => {
      console.log('WebSocket disconnected');
      document.getElementById('status-pill').textContent = '离线';
      setTimeout(() => this.connect(), this.reconnectDelay);
    };
  }

  handleMessage(message) {
    switch(message.type) {
      case 'price_update':
        updatePrice(message.data);
        break;
      case 'indicators_update':
        updateIndicators(message.data);
        break;
      case 'signal_alert':
        showSignalAlert(message.data);
        break;
    }
  }
}
```

### 5.3 自动重连

- 连接断开后 3 秒自动重连
- 最多重试 10 次
- 重连成功后重新加载数据

## 6. K线图和成交量图

### 6.1 数据聚合策略

由于当前只有单一价格点(每3分钟一个),需要聚合生成K线数据:

**聚合周期:**
- 5分钟: 聚合 2 个数据点
- 15分钟: 聚合 5 个数据点
- 1小时: 聚合 20 个数据点
- 4小时: 聚合 80 个数据点
- 1天: 聚合 480 个数据点

**K线数据生成:**
```python
{
  "timestamp": "2026-03-16T10:00:00",
  "open": 485.0,   # 周期第一个价格
  "high": 486.5,   # 周期最高价
  "low": 484.2,    # 周期最低价
  "close": 485.8,  # 周期最后价格
  "volume": 20     # 数据点数量(替代成交量)
}
```

### 6.2 成交量替代指标

由于数据源不提供真实成交量,使用以下替代指标:

1. **数据点数量:** 周期内采集到的数据点数
2. **价格波动幅度:** (最高价 - 最低价) / 最低价 * 100
3. **价格变化率:** |收盘价 - 开盘价| / 开盘价 * 100

显示为"活跃度"而非"成交量"。

### 6.3 实现设计

**后端实现:**

文件: `app/api/price.py`

新增端点:
```python
@router.get("/candlestick")
def get_candlestick_data(
    days: int = Query(7, ge=1, le=365),
    interval: str = Query("1h", description="5m, 15m, 1h, 4h, 1d")
):
    """获取K线数据"""
    # 查询原始数据
    # 按时间周期聚合
    # 生成 OHLC 数据
    # 计算活跃度指标
    return {"items": candlestick_data}
```

**前端实现:**

使用 Chart.js 的 chartjs-chart-financial 插件:

```javascript
// 安装: 在 index.html 添加
<script src="https://cdn.jsdelivr.net/npm/chartjs-chart-financial@0.2.0"></script>

// 创建K线图
function buildCandlestickChart(data) {
  new Chart(ctx, {
    type: 'candlestick',
    data: {
      datasets: [{
        label: '黄金价格',
        data: data.map(item => ({
          x: new Date(item.timestamp),
          o: item.open,
          h: item.high,
          l: item.low,
          c: item.close
        }))
      }]
    }
  });
}
```

**图表切换:**

在界面上添加图表类型切换按钮:
- 折线图(默认)
- K线图
- K线图 + MACD
- K线图 + 活跃度

### 6.4 活跃度图表

在K线图下方显示活跃度柱状图:

```javascript
{
  type: 'bar',
  label: '活跃度',
  data: volumeData,
  backgroundColor: (context) => {
    const index = context.dataIndex;
    const candle = candlestickData[index];
    return candle.close >= candle.open ?
      'rgba(139, 211, 199, 0.5)' :  // 上涨-绿色
      'rgba(240, 128, 128, 0.5)';   // 下跌-红色
  }
}
```

## 7. 数据库变更

无需修改现有数据库结构,所有新功能使用现有数据。

## 8. 配置更新

更新 `config.py`:

```python
# MACD 配置
macd_fast: int = 12
macd_slow: int = 26
macd_signal: int = 9

# WebSocket 配置
websocket_enabled: bool = True
websocket_ping_interval: int = 30

# 图表配置
default_chart_type: str = "line"  # line, candlestick
candlestick_interval: str = "1h"  # 5m, 15m, 1h, 4h, 1d
```

## 9. 前端界面更新

### 9.1 新增组件

**智能建议卡片:**
```html
<article class="card advice-card">
  <div class="card-header">
    <span>智能建议</span>
    <span class="score" id="advice-score">--</span>
  </div>
  <div class="advice-content">
    <p class="recommendation" id="recommendation">--</p>
    <p class="market-state" id="market-state">--</p>
    <ul class="insights" id="insights-list"></ul>
    <ul class="risks" id="risks-list"></ul>
  </div>
</article>
```

**图表类型切换:**
```html
<div class="chart-type-switch">
  <button data-type="line" class="active">折线图</button>
  <button data-type="candlestick">K线图</button>
  <button data-type="candlestick-macd">K线+MACD</button>
</div>
```

**MACD 指标显示:**
```html
<div class="macd-indicators">
  <span>MACD: <span id="macd-value">--</span></span>
  <span>信号: <span id="macd-signal-value">--</span></span>
  <span>柱状: <span id="macd-histogram-value">--</span></span>
</div>
```

### 9.2 样式更新

添加到 `static/css/style.css`:

```css
.advice-card {
  grid-column: span 2;
}

.score {
  font-size: 1.5rem;
  font-weight: 700;
  padding: 0.25rem 0.75rem;
  border-radius: 1rem;
}

.score.buy { background: rgba(139, 211, 199, 0.2); color: #8bd3c7; }
.score.hold { background: rgba(240, 208, 139, 0.2); color: #f0d08b; }
.score.sell { background: rgba(240, 128, 128, 0.2); color: #f08080; }

.insights, .risks {
  list-style: none;
  padding: 0;
}

.insights li::before { content: "✓ "; color: #8bd3c7; }
.risks li::before { content: "⚠ "; color: #f0d08b; }
```

## 10. 测试策略

### 10.1 单元测试

新增测试文件: `tests/test_macd.py`
```python
def test_calculate_macd_returns_correct_values()
def test_macd_golden_cross_detection()
def test_macd_death_cross_detection()
```

新增测试文件: `tests/test_advisor.py`
```python
def test_calculate_score_oversold_condition()
def test_generate_recommendation_strong_buy()
def test_identify_risks_downtrend()
```

新增测试文件: `tests/test_websocket.py`
```python
def test_websocket_connection()
def test_broadcast_price_update()
def test_auto_reconnect()
```

### 10.2 集成测试

- 测试完整的数据流: 采集 → 分析 → WebSocket 推送
- 测试 K线数据聚合准确性
- 测试智能建议生成逻辑

## 11. 实施顺序

1. **修复测试** (30分钟)
   - 修复 `test_price_history_downsample_interval`
   - 确保所有测试通过

2. **添加 MACD 指标** (1小时)
   - 后端计算逻辑
   - API 集成
   - 单元测试

3. **智能解读引擎** (2小时)
   - 评分算法
   - 建议生成
   - API 端点
   - 单元测试

4. **WebSocket 实时推送** (1.5小时)
   - 后端 WebSocket 服务
   - 调度器集成
   - 前端客户端
   - 自动重连

5. **K线图和成交量图** (2小时)
   - 数据聚合逻辑
   - K线 API 端点
   - 前端图表实现
   - 图表切换功能

6. **前端界面整合** (1小时)
   - 智能建议卡片
   - MACD 子图
   - 样式优化
   - 响应式调整

**总计:** 约 7.5-8 小时

## 12. 风险与注意事项

### 12.1 性能考虑

- WebSocket 连接数限制(建议最多 100 个并发连接)
- MACD 计算对大数据集的性能影响
- K线数据聚合的内存占用

### 12.2 兼容性

- Chart.js financial 插件的浏览器兼容性
- WebSocket 在旧浏览器的降级方案

### 12.3 数据准确性

- 成交量替代指标的局限性
- 智能建议的免责声明

## 13. 未来优化方向

1. **机器学习预测** - 基于历史数据训练预测模型
2. **多品种支持** - 支持白银、铂金等其他贵金属
3. **回测功能** - 验证买入策略的历史表现
4. **移动端优化** - PWA 支持,离线功能
5. **用户自定义策略** - 允许用户配置自己的买入条件

## 14. 总结

本次增强将显著提升系统的分析能力和用户体验:

- **MACD 指标** 提供更准确的趋势判断
- **智能解读** 降低用户分析门槛,提供专业建议
- **WebSocket** 实现真正的实时监控
- **K线图** 提供更专业的数据展示方式

所有功能都基于现有架构,无需大规模重构,风险可控。
