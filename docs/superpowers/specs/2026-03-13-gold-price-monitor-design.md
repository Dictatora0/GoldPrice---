# 黄金价格监控系统设计文档

**日期:** 2026-03-13
**项目:** GoldPrice - 黄金价格智能监控与分析系统

## 1. 项目概述

开发一个黄金价格监控系统,实现以下核心功能:
- 从多个数据源实时采集黄金价格数据(以人民币/克为单位)
- 存储长期历史数据(1年以上)用于趋势分析
- 使用技术指标智能分析价格趋势,识别买入时机
- 通过 macOS 系统通知提醒用户低价买入机会
- 提供 Web 界面展示实时价格图表和历史数据

## 2. 技术栈选择

**方案:** Python + FastAPI + SQLite

**核心技术:**
- **后端框架:** FastAPI (高性能 Web 框架)
- **定时任务:** APScheduler (每 3 分钟采集一次数据)
- **数据库:** SQLite (轻量级,无需额外服务)
- **数据分析:** pandas, numpy, scikit-learn
- **前端图表:** Chart.js
- **系统通知:** pync (macOS 通知库)

**选择理由:**
1. Python 数据科学生态成熟,适合智能分析
2. FastAPI 开发效率高,自带交互式 API 文档
3. SQLite 轻量级,适合个人使用
4. 扩展性好,后续可添加更复杂的机器学习模型

## 3. 系统架构

系统分为四个核心模块:

### 3.1 数据采集模块
从多个数据源定时抓取黄金价格并转换为人民币单位。

### 3.2 数据存储模块
使用 SQLite 数据库持久化存储历史价格数据。

### 3.3 智能分析模块
使用技术指标分析价格趋势,识别买入时机。

### 3.4 Web 服务模块
提供 RESTful API 和 Web 界面展示数据。

## 4. 数据采集模块详细设计

### 4.1 数据源选择

**多数据源策略(以国内金价为主):**
1. **新浪财经** - 国内黄金价格(人民币/克),无请求限制,主要数据源
2. **东方财富网** - 国内黄金价格(人民币/克),无请求限制,备用数据源
3. **金投网** - 国内黄金价格(人民币/克),无请求限制,备用数据源

**选择理由:**
- 国内数据源直接提供人民币/克价格,无需汇率转换
- 价格更贴近国内市场实际购买价格
- 无 API 请求限制,可以更频繁采集
- 数据稳定性好,适合长期监控

### 4.2 数据处理流程

1. **并发请求:** 每 3 分钟并发请求所有国内数据源
2. **数据验证:** 多源价格差异超过 3% 时记录异常
3. **均价计算:** 取所有有效数据源的平均值作为最终价格
4. **容错机制:** 单个数据源失败不影响整体,至少需要 1 个数据源成功

### 4.3 数据模型

```python
{
  "timestamp": "2026-03-13 18:45:00",
  "price_cny_per_gram": 485.32,
  "sources": {
    "sina": 485.10,
    "eastmoney": 485.50,
    "gold_cn": 485.35
  }
}
```

### 4.4 采集器设计

- **基类:** `BaseCollector` 定义统一接口
- **具体实现:** `SinaCollector`, `EastMoneyCollector`, `GoldCNCollector`
- **错误处理:** 网络超时、数据格式错误等异常处理
- **日志记录:** 记录每次采集的成功/失败状态

## 5. 数据存储模块详细设计

### 5.1 数据库表结构

**price_history 表** - 存储每次采集的价格数据
```sql
CREATE TABLE price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    price_cny_per_gram REAL NOT NULL,
    source_count INTEGER NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_timestamp ON price_history(timestamp);
```

**price_sources 表** - 存储各数据源的原始价格
```sql
CREATE TABLE price_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    price_history_id INTEGER NOT NULL,
    source_name VARCHAR(50) NOT NULL,
    price_cny_per_gram REAL NOT NULL,
    is_valid BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (price_history_id) REFERENCES price_history(id)
);
```

**analysis_signals 表** - 存储分析信号记录
```sql
CREATE TABLE analysis_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    signal_type VARCHAR(20) NOT NULL,
    price_cny_per_gram REAL NOT NULL,
    indicators TEXT,  -- JSON serialized string
    notified BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 5.2 数据保留策略

- 保留所有历史数据(1年以上)
- 每天凌晨 2 点自动备份数据库文件到 `data/backups/`
- 数据库文件位置: `data/gold_price.db`
- 定期执行 VACUUM 优化数据库文件大小

### 5.3 查询优化

- `timestamp` 字段建立索引,加速时间范围查询
- 使用 SQLAlchemy ORM 进行数据库操作
- 批量插入优化性能

## 6. 智能分析模块详细设计

### 6.1 技术指标计算

使用以下技术指标进行综合分析:

1. **移动平均线(MA)**
   - 7 天短期均线
   - 30 天中期均线
   - 90 天长期均线

2. **布林带(Bollinger Bands)**
   - 基于 20 天移动平均线
   - 标准差倍数: 2
   - 上轨 = MA20 + 2σ
   - 下轨 = MA20 - 2σ

3. **相对强弱指标(RSI)**
   - 周期: 14 天
   - 超买区: RSI > 70
   - 超卖区: RSI < 30

4. **价格波动率**
   - 计算最近 30 天的标准差
   - 用于判断市场波动程度

### 6.2 买入信号判断逻辑

当同时满足以下条件时触发买入提醒:

1. **价格位置:** 当前价格低于布林带下轨(价格处于低位)
2. **超卖状态:** RSI < 30
3. **相对均线:** 当前价格低于 30 天移动平均线 2% 以上
4. **趋势反转:** 最近 3 天价格呈下降趋势但波动率开始收窄(可能触底反弹)

### 6.3 分析流程

```
新数据采集 → 计算技术指标 → 判断买入信号 → 记录信号 → 发送通知(如果满足条件)
```

### 6.4 通知策略

- 同一买入信号 24 小时内只通知一次,避免重复打扰
- 通知内容包括:
  - 当前价格
  - 相比 30 天均价的跌幅百分比
  - 各项技术指标数值
  - 建议理由

### 6.5 分析器实现

- `IndicatorCalculator` 类: 计算各项技术指标
- `SignalDetector` 类: 判断买入信号
- 使用 pandas 进行时间序列数据处理
- 使用 numpy 进行数值计算

## 7. Web 服务模块详细设计

### 7.1 RESTful API 端点

**价格相关 API:**
- `GET /api/price/current` - 获取当前最新价格
  - 返回: 最新价格、时间戳、数据源数量
- `GET /api/price/history?days=30&interval=1h` - 获取历史价格数据
  - 参数: days(天数), interval(数据间隔)
  - 返回: 时间序列价格数据

**分析相关 API:**
- `GET /api/analysis/indicators` - 获取当前技术指标
  - 返回: MA、布林带、RSI、波动率等指标
- `GET /api/analysis/signals?days=7` - 获取历史买入信号记录
  - 参数: days(查询天数)
  - 返回: 信号列表及详细信息

**系统 API:**
- `GET /api/health` - 服务健康检查
  - 返回: 服务状态、数据库连接、最后采集时间

### 7.2 Web 界面设计

**首页布局:**
1. **顶部卡片:** 显示当前价格、24小时涨跌幅、关键指标
2. **主图表区:** 使用 Chart.js 绘制价格走势图
   - 折线图显示价格趋势
   - 叠加显示移动平均线
   - 叠加显示布林带上下轨
   - 标注买入信号点(绿色标记)
3. **时间范围选择:** 7天/30天/90天/1年/全部
4. **指标面板:** 显示当前 RSI、波动率等指标
5. **信号历史:** 列表显示最近的买入信号

**技术实现:**
- 使用原生 HTML + CSS + JavaScript
- Chart.js 用于图表渲染
- Fetch API 调用后端接口
- 响应式设计,支持移动端访问

### 7.3 后台服务

**定时任务:**
- 使用 APScheduler 调度器
- 每 3 分钟执行数据采集任务
- 每次采集后立即执行分析任务
- 每天凌晨 2 点执行数据库备份任务

**服务启动:**
- FastAPI 应用使用 uvicorn 运行
- 默认端口: 8000
- 启动时自动初始化数据库表
- 提供命令行参数控制功能开关

**命令行参数:**
```bash
python run.py --port 8000 --no-notify  # 禁用通知
python run.py --interval 5             # 设置采集间隔(分钟)
```

### 7.4 macOS 通知实现

使用 `pync` 库发送系统通知:

```python
import pync

pync.notify(
    title="黄金价格买入提醒",
    message=f"当前价格: ¥{price}/克\n跌幅: {drop_percent}%\nRSI: {rsi}",
    sound="default"
)
```

**通知内容示例:**
```
标题: 黄金价格买入提醒
内容:
当前价格: ¥485.32/克
跌幅: -3.2% (相比30天均价)
RSI: 28 (超卖)
建议: 价格触及布林带下轨,可能反弹
```

## 8. 项目结构

```
GoldPrice/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 应用入口
│   ├── scheduler.py         # APScheduler 定时任务配置
│   ├── models.py            # SQLAlchemy 数据模型
│   ├── database.py          # 数据库连接配置
│   ├── collectors/          # 数据采集模块
│   │   ├── __init__.py
│   │   ├── base.py          # 采集器基类
│   │   ├── sina.py          # 新浪财经采集器
│   │   ├── eastmoney.py     # 东方财富采集器
│   │   └── gold_cn.py       # 金投网采集器
│   ├── analyzers/           # 智能分析模块
│   │   ├── __init__.py
│   │   ├── indicators.py    # 技术指标计算
│   │   └── signals.py       # 买入信号判断
│   ├── notifiers/           # 通知模块
│   │   ├── __init__.py
│   │   └── macos.py         # macOS 通知实现
│   └── api/                 # API 路由
│       ├── __init__.py
│       ├── price.py         # 价格相关 API
│       └── analysis.py      # 分析相关 API
├── static/                  # 静态文件
│   ├── css/
│   │   └── style.css        # 样式文件
│   ├── js/
│   │   └── chart.js         # 图表展示逻辑
│   └── index.html           # Web 界面
├── data/                    # 数据目录
│   ├── gold_price.db        # SQLite 数据库
│   └── backups/             # 数据库备份目录
├── docs/                    # 文档目录
│   └── superpowers/
│       └── specs/
│           └── 2026-03-13-gold-price-monitor-design.md
├── tests/                   # 测试目录
│   ├── test_collectors.py
│   ├── test_analyzers.py
│   └── test_api.py
├── .env.example             # 环境变量示例
├── .gitignore
├── config.py                # 配置文件
├── requirements.txt         # Python 依赖
├── run.py                   # 启动脚本
└── README.md                # 项目说明
```

## 9. 配置管理

### 9.1 环境变量 (.env)

```env
# 数据采集配置
COLLECTION_INTERVAL=3  # 分钟
DATA_SOURCE_TIMEOUT=10  # 秒

# 分析配置
RSI_PERIOD=14
BOLLINGER_PERIOD=20
BOLLINGER_STD=2
MA_SHORT=7
MA_MEDIUM=30
MA_LONG=90

# 通知配置
ENABLE_NOTIFICATION=true
NOTIFICATION_COOLDOWN=24  # 小时

# 数据库配置
DATABASE_PATH=data/gold_price.db
BACKUP_ENABLED=true
BACKUP_TIME=02:00

# Web 服务配置
HOST=0.0.0.0
PORT=8000
DEBUG=false
```

### 9.2 配置文件 (config.py)

使用 pydantic 进行配置管理:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    collection_interval: int = 3
    data_source_timeout: int = 10
    # ... 其他配置

    class Config:
        env_file = ".env"
```

## 10. 依赖包 (requirements.txt)

```
fastapi==0.115.0
uvicorn[standard]==0.32.0
sqlalchemy==2.0.36
apscheduler==3.10.4
pandas==2.2.3
numpy==2.1.3
scikit-learn==1.5.2
requests==2.32.3
pync==2.0.3
python-dotenv==1.0.1
pydantic-settings==2.6.1
aiohttp==3.11.7
pytest==8.3.4
pytest-asyncio==0.24.0
httpx==0.28.1
```

## 11. 错误处理与日志

### 11.1 错误处理策略

1. **数据采集错误:**
   - 网络超时: 重试 3 次,间隔 5 秒
   - 数据格式错误: 标记数据源为无效,继续其他源

2. **数据库错误:**
   - 连接失败: 重试连接,失败后停止服务
   - 写入失败: 记录错误日志,不影响下次采集

3. **分析错误:**
   - 数据不足: 跳过分析,等待更多数据
   - 计算异常: 记录错误,使用默认值

### 11.2 日志配置

使用 Python logging 模块:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)
```

**日志级别:**
- INFO: 正常操作(数据采集成功、信号触发)
- WARNING: 异常但可恢复(单个数据源失败)
- ERROR: 严重错误(数据库连接失败)

## 12. 测试策略

### 12.1 单元测试

- 测试各个采集器的数据获取和转换逻辑
- 测试技术指标计算的准确性
- 测试信号判断逻辑

### 12.2 集成测试

- 测试完整的数据采集→存储→分析流程
- 测试 API 端点的响应
- 测试通知功能

### 12.3 测试工具

- pytest: 测试框架
- pytest-asyncio: 异步测试支持
- httpx: API 测试客户端

## 13. 部署与运行

### 13.1 初始化

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API keys

# 初始化数据库
python run.py --init-db
```

### 13.2 启动服务

```bash
# 启动服务(默认配置)
python run.py

# 自定义配置启动
python run.py --port 8080 --interval 5

# 禁用通知启动
python run.py --no-notify
```

### 13.3 访问界面

浏览器访问: `http://localhost:8000`

## 14. 未来优化方向

1. **更多数据源:** 增加更多国内外金价数据源
2. **高级分析:** 引入机器学习模型预测价格趋势
3. **多通知渠道:** 支持邮件、微信、Telegram 通知
4. **移动端应用:** 开发 iOS/Android 应用
5. **用户系统:** 支持多用户,个性化配置
6. **实时推送:** WebSocket 实时推送价格更新
7. **回测功能:** 基于历史数据回测买入策略效果

## 15. 总结

本设计文档详细描述了黄金价格监控系统的架构、模块设计和实现细节。系统采用 Python + FastAPI + SQLite 技术栈,实现了多数据源价格采集、智能趋势分析、macOS 通知提醒和 Web 可视化展示等核心功能。设计注重模块化、可扩展性和用户体验,为后续优化和功能扩展预留了空间。
