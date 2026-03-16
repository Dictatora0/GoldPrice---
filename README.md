# GoldPrice - 黄金价格智能监控系统

一个功能完善的黄金价格监控系统,支持多数据源采集、技术指标分析、智能买入建议、实时推送和专业图表展示。

## ✨ 核心功能

- 🔄 **多数据源采集** - 新浪财经、东方财富、金投网
- 📊 **技术指标分析** - RSI、布林带、MACD、移动平均线
- 🤖 **智能买入建议** - 多指标综合评分,自动生成投资建议
- ⚡ **实时推送** - WebSocket 实时更新价格和指标
- 📈 **专业图表** - 折线图、K线图、活跃度指标
- 🔔 **系统通知** - macOS 通知提醒买入时机
- 💾 **数据存储** - SQLite 持久化存储,自动备份
- 🚀 **Redis缓存** - 高性能缓存层,支持高并发访问
- 📊 **Prometheus监控** - 完整的指标收集和监控
- 🔍 **结构化日志** - PostgreSQL日志存储,Web日志查看器
- 🔔 **多渠道告警** - macOS通知、Webhook、Slack集成

## 🚀 快速开始

### 方式一: 本地运行

#### 1. 安装依赖

```bash
pip install -r requirements.txt
```

#### 2. 配置环境变量

```bash
cp .env.example .env
# 根据需要编辑 .env 文件
```

#### 3. 初始化数据库

```bash
./manage.sh init-db
# 或
python run.py --init-db
```

#### 4. 启动服务

```bash
./manage.sh start
# 或
python run.py
```

#### 5. 访问界面

打开浏览器访问: http://localhost:8000

### 方式二: Docker Compose (推荐)

```bash
# 启动所有服务(包括Redis和PostgreSQL)
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

访问地址:
- 主应用: http://localhost:8000
- Prometheus指标: http://localhost:9090/metrics
- 健康检查: http://localhost:8000/healthcheck

## 📋 管理命令

使用 `manage.sh` 脚本管理服务:

```bash
./manage.sh start      # 启动服务
./manage.sh stop       # 停止服务
./manage.sh restart    # 重启服务
./manage.sh status     # 查看状态
./manage.sh logs       # 查看日志
./manage.sh test       # 运行测试
./manage.sh init-db    # 初始化数据库
```

## 🎯 使用指南

### 查看实时价格

- 打开主页面,顶部显示最新价格
- WebSocket 自动推送实时更新
- 状态指示器显示连接状态(在线/离线)

### 查看智能建议

系统自动分析技术指标并生成买入建议:

- **评分:** 0-100分(越低越适合买入)
- **建议:** 强烈推荐/推荐/观望/不推荐/强烈不推荐
- **洞察:** 关键指标解读
- **风险:** 风险因素识别

### 切换图表类型

1. **折线图模式** - 显示价格趋势、移动平均线、布林带
2. **K线图模式** - 显示OHLC数据、活跃度指标
   - 支持 1小时/4小时/1天 时间间隔

### 接收买入提醒

1. 授权浏览器通知权限
2. 系统检测到买入信号时自动推送
3. 24小时内同一信号只通知一次

## 📊 技术指标说明

### RSI (相对强弱指标)
- **周期:** 14天
- **超买:** RSI > 70
- **超卖:** RSI < 30

### 布林带
- **周期:** 20天
- **标准差:** 2倍
- **上轨:** MA20 + 2σ
- **下轨:** MA20 - 2σ

### MACD (指数平滑异同移动平均线)
- **快线:** 12日EMA
- **慢线:** 26日EMA
- **信号线:** 9日EMA
- **金叉:** MACD上穿信号线(买入信号)
- **死叉:** MACD下穿信号线(卖出信号)

### 移动平均线
- **短期:** 7天
- **中期:** 30天
- **长期:** 90天

## 🔧 配置说明

编辑 `.env` 文件自定义配置:

```bash
# 数据采集
COLLECTION_INTERVAL=3        # 采集间隔(分钟)
DATA_SOURCE_TIMEOUT=10       # 数据源超时(秒)

# 技术指标
RSI_PERIOD=14               # RSI周期
BOLLINGER_PERIOD=20         # 布林带周期
MACD_FAST_PERIOD=12         # MACD快线周期
MACD_SLOW_PERIOD=26         # MACD慢线周期
MACD_SIGNAL_PERIOD=9        # MACD信号线周期

# 通知
ENABLE_NOTIFICATION=true    # 启用通知
NOTIFICATION_COOLDOWN=24    # 通知冷却时间(小时)

# 数据库
DATABASE_PATH=data/gold_price.db
BACKUP_ENABLED=true         # 启用自动备份
BACKUP_TIME=02:00          # 备份时间

# Web服务
HOST=0.0.0.0
PORT=8000
DEBUG=false
```

## 🌐 API 端点

### 价格相关
- `GET /api/price/current` - 获取当前价格
- `GET /api/price/history` - 获取历史价格
- `GET /api/price/candlestick` - 获取K线数据

### 分析相关
- `GET /api/analysis/indicators` - 获取技术指标
- `GET /api/analysis/signals` - 获取买入信号历史
- `GET /api/analysis/advice` - 获取智能建议

### 系统相关
- `GET /api/health` - 健康检查
- `WS /ws` - WebSocket连接

### API 示例

```bash
# 获取当前价格
curl http://localhost:8000/api/price/current

# 获取智能建议
curl http://localhost:8000/api/analysis/advice

# 获取K线数据
curl "http://localhost:8000/api/price/candlestick?days=7&interval=1h"
```

## 🧪 测试

运行所有测试:

```bash
./manage.sh test
# 或
python -m pytest tests/ -v
```

运行特定测试:

```bash
python -m pytest tests/test_macd.py -v
python -m pytest tests/test_advisor.py -v
python -m pytest tests/test_candlestick.py -v
```

## 📁 项目结构

```
GoldPrice/
├── app/                    # 应用代码
│   ├── analyzers/         # 分析模块
│   │   ├── indicators.py  # 技术指标(RSI, MACD, 布林带)
│   │   ├── advisor.py     # 智能顾问
│   │   └── signals.py     # 买入信号检测
│   ├── api/               # API端点
│   │   ├── price.py       # 价格API
│   │   ├── analysis.py    # 分析API
│   │   ├── websocket.py   # WebSocket
│   │   └── health.py      # 健康检查
│   ├── collectors/        # 数据采集器
│   ├── notifiers/         # 通知模块
│   ├── main.py           # FastAPI应用
│   └── scheduler.py      # 定时任务
├── static/               # 静态文件
│   ├── js/
│   │   ├── chart.js      # 折线图
│   │   ├── candlestick.js # K线图
│   │   └── websocket.js  # WebSocket客户端
│   ├── css/
│   │   └── style.css     # 样式
│   └── index.html        # 主页面
├── tests/                # 测试文件
├── docs/                 # 文档
├── data/                 # 数据目录
├── logs/                 # 日志目录
├── manage.sh            # 管理脚本
├── run.py               # 启动脚本
├── config.py            # 配置
└── requirements.txt     # 依赖
```

## 🔒 安全说明

- WebSocket 连接限制(最多100个并发)
- 自动清理失败连接,防止内存泄漏
- 所有投资建议包含免责声明
- 数据库连接安全关闭

## ⚠️ 免责声明

本系统提供的所有分析和建议仅供参考,不构成投资建议。投资有风险,入市需谨慎。请根据自身情况做出投资决策。

## 📝 更新日志

### v1.1.0 (2026-03-16)
- ✅ 新增 MACD 指标分析
- ✅ 新增智能买入建议引擎
- ✅ 新增 WebSocket 实时推送
- ✅ 新增 K线图和活跃度指标
- ✅ 修复测试问题
- ✅ 54个测试全部通过

### v1.0.0 (2026-03-13)
- ✅ 多数据源价格采集
- ✅ RSI、布林带、移动平均线指标
- ✅ 买入信号检测
- ✅ macOS 系统通知
- ✅ Web 界面展示

## 🤝 贡献

欢迎提交 Issue 和 Pull Request!

## 📄 许可证

MIT License

## 📧 联系方式

如有问题或建议,请提交 Issue。

---

**Made with ❤️ by Claude Sonnet 4.6**
