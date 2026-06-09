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
pip install -r requirements-dev.txt
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

## ▶️ 启动命令速查（可直接复制）

本地前台启动（适合调试）：

```bash
cp .env.example .env
python run.py --init-db
python run.py
```

本地后台启动（推荐日常使用）：

```bash
cp .env.example .env
./manage.sh init-db
./manage.sh start
./manage.sh status
./manage.sh daemon-check
```

后台停止/重启：

```bash
./manage.sh stop
./manage.sh restart
```

Docker Compose 启动：

```bash
cp .env.example .env
docker-compose up -d
docker-compose logs -f
docker-compose down
```

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

## 🛠️ 后台常驻运行（稳定模式）

推荐用 `manage.sh` 作为常驻启动入口，它已做了后台自检：

```bash
# 1) 初始化
cp .env.example .env
./manage.sh init-db

# 2) 后台启动（会等待健康检查通过）
./manage.sh start

# 3) 查看状态
./manage.sh status
./manage.sh daemon-check

# 4) 查看日志
./manage.sh logs 120 --no-follow
```

说明：
- `start` 不再只看进程存活，会轮询 `GET /api/health`，确认系统真正可用后才返回成功。
- `daemon-check` 会输出健康 JSON，便于确认采集调度、告警检测循环是否都在后台运行。
- 若健康检查失败，脚本会打印日志尾部，便于快速定位问题。

可调参数（按需）：
- `HEALTHCHECK_TIMEOUT_SECONDS`：启动后健康探测超时（默认 25 秒）
- `HEALTHCHECK_INTERVAL_SECONDS`：健康探测轮询间隔（默认 1 秒）
- `HEALTH_ENDPOINT_PATH`：健康检查路径（默认 `/api/health`）

后台常驻的关键检查项：
- `runtime.scheduler.running=true`：采集调度器正在运行
- `runtime.alerts_loop.running=true`：自定义预警/系统告警检测循环正在运行
- `runtime.details.scheduler.collect.last_success_at`：最近一次采集成功时间
- `runtime.details.alerts_loop.last_success_at`：最近一次告警检测成功时间

最小排障清单：
1. `./manage.sh daemon-check` 看 `status` 是否 `ok`。
2. 若 `runtime.scheduler.running=false`，先看 `logs/server.out` 是否缺少 `apscheduler` 依赖。
3. 若 `runtime.alerts_loop.running=false`，检查启动日志中是否有 `Alert evaluation error`。
4. 若 `data.ok=false`（数据过期），检查采集源连通性和 `COLLECTION_INTERVAL`。

真实系统 smoke test（启动、初始化、采集一次、访问关键 API、检查前端可取到数据）：

```bash
BASE_URL=http://127.0.0.1:8000 bash scripts/smoke_test.sh
```

说明：
- smoke test 会在服务不可达时调用 `./manage.sh start`。
- 默认会执行一次真实行情采集，需要网络可用；如只想检查已运行服务和 API，可设置 `RUN_COLLECT=false`。
- 如果脚本启动了后台服务，会保留服务运行，便于继续打开网页检查。

## 🧭 数据可信度说明

- **SGE 主源**：优先使用上海黄金交易所官网延时行情，作为国内金价判断的高可信锚点；页面“当前主源”显示可用或缺席状态。
- **备用源**：新浪财经、东方财富、金投网等用于兜底和交叉校验；当主源缺席时，系统会按可信度加权聚合，但页面会降低数据源质量提示。
- **宏观换算价**：国际金价/美元汇率换算为人民币克价，用于观察内外盘价差和宏观相关性，不等同于国内可成交价格。
- **预测模型**：基于历史价格序列估算未来概率和区间，只表示统计倾向；前端会展示样本数、时间基准和“样本不足/低可信”等标记，不能当作确定收益承诺。
- **策略回测**：历史信号表现会按当前市场环境分层，优先参考当前 regime 对应样本；样本不足时应按观望处理。

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
COLLECTION_INTERVAL=30       # 采集间隔(秒)
DATA_SOURCE_TIMEOUT=10       # 数据源超时(秒)
PRICE_GUARD_REFERENCE_MAX_AGE_HOURS=12  # 价格守卫参考数据最大时效(小时)

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
BACKUP_TIME=02:00           # 备份时间
DATABASE_POOL_SIZE=10        # 连接池大小
DATABASE_MAX_OVERFLOW=20     # 最大溢出连接数

# Redis缓存
REDIS_ENABLED=true          # 启用Redis缓存
REDIS_HOST=localhost        # Redis主机
REDIS_PORT=6379             # Redis端口
REDIS_PASSWORD=__SET_REDIS_PASSWORD_IF_NEEDED__   # 可选
CACHE_INDICATORS_TTL=120    # 指标缓存时间(秒)
CACHE_PRICE_TTL=120         # 价格缓存时间(秒)

# PostgreSQL日志
LOG_TO_POSTGRES=false       # 启用PostgreSQL日志存储
POSTGRES_HOST=localhost     # PostgreSQL主机
POSTGRES_PORT=5432          # PostgreSQL端口
POSTGRES_DB=goldprice_logs  # PostgreSQL数据库
POSTGRES_USER=goldprice     # PostgreSQL用户名
POSTGRES_PASSWORD=__SET_A_STRONG_PASSWORD__       # 仅在 LOG_TO_POSTGRES=true 时必填
LOG_RETENTION_DAYS=30       # 日志保留天数

# 监控告警
PROMETHEUS_ENABLED=true    # 启用Prometheus指标
ALERT_COOLDOWN_MINUTES=30  # 告警冷却时间(分钟)

# Web服务
HOST=0.0.0.0
PORT=8000
DEBUG=false
```

## 🚀 性能与可观测性特性

### 数据库连接池
- 复用数据库连接,提升性能
- 可配置连接池大小和溢出数
- 自动连接健康检查
- 性能提升: 数据库查询速度提升50%

### Redis缓存层
- 缓存昂贵的计算(指标、信号、分析)
- 每种缓存类型可配置TTL
- Redis不可用时优雅降级
- 缓存命中率: 典型场景70-90%
- 性能提升: API响应时间减少80-90%(缓存命中时)

### Prometheus指标监控
- 全面的操作指标收集
- 采集成功/失败追踪
- 缓存命中/未命中比率
- 系统资源监控
- 指标端点: `http://localhost:8000/metrics`

### PostgreSQL结构化日志
- 双重日志: 文件 + PostgreSQL数据库
- 可查询的日志历史
- 自动保留期清理
- 日志查看器API: `http://localhost:8000/api/logs`

### 告警规则
- 采集器故障检测
- 价格异常波动告警
- 系统资源监控
- 多渠道通知(macOS、Webhook、Slack)

## 🌐 API 端点

### 价格相关
- `GET /api/price/current` - 获取当前价格
- `GET /api/price/history` - 获取历史价格
- `GET /api/price/candlestick` - 获取K线数据

### 分析相关
- `GET /api/analysis/indicators` - 获取技术指标
- `GET /api/analysis/signals` - 获取买入信号历史
- `GET /api/analysis/advice` - 获取智能建议
- `GET /api/analysis/signal-performance` - 获取历史信号回测表现
- `GET /api/analysis/confidence-center` - 获取策略体检与建议可信度中心
- `GET /api/analysis/support-resistance` - 获取自动识别支撑/阻力位

### 预警相关
- `GET /api/alerts` - 获取自定义预警规则
- `POST /api/alerts` - 新增预警规则
- `PATCH /api/alerts/{rule_id}` - 修改预警规则
- `DELETE /api/alerts/{rule_id}` - 删除预警规则
- `GET /api/alerts/deliveries` - 查看通知发送日志（支持 channel/status 过滤）

### 监控相关
- `GET /api/health` - 健康检查
- `GET /metrics` - Prometheus指标
- `GET /api/logs` - 日志查看器(支持过滤)

### 实时通信
- `WS /ws` - WebSocket连接

### API 示例

```bash
# 获取当前价格
curl http://localhost:8000/api/price/current

# 获取智能建议
curl http://localhost:8000/api/analysis/advice

# 获取信号回测统计(默认3/7/30天窗口)
curl "http://localhost:8000/api/analysis/signal-performance?window_days=180&horizons=3,7,30"

# 获取策略体检与当前建议可信度
curl "http://localhost:8000/api/analysis/confidence-center?window_days=180&horizons=3,7,30"

# 获取支撑/阻力关键位
curl "http://localhost:8000/api/analysis/support-resistance?window_days=180&pivot_window=5"

# 新增自定义预警：价格跌破 580 元
curl -X POST "http://localhost:8000/api/alerts?name=price-floor-580&rule_type=price_below&threshold=580&channels=system,email,wechat&cooldown_minutes=60&enabled=true"

# 获取K线数据
curl "http://localhost:8000/api/price/candlestick?days=7&interval=1h"

# 查看Prometheus指标
curl http://localhost:8000/metrics

# 查看日志(最近100条ERROR级别)
curl "http://localhost:8000/api/logs?level=ERROR&limit=100"
```

## 📊 监控与日志

### Prometheus指标
访问 `http://localhost:8000/metrics` 查看所有指标

关键指标:
- `gold_http_request_duration_seconds` - API延迟
- `gold_cache_hits_total` / `gold_cache_misses_total` - 缓存性能
- `gold_collector_success_total` / `gold_collector_failure_total` - 采集健康度
- `gold_system_cpu_percent` / `gold_system_memory_percent` - 系统资源

### 日志查看器
访问 `http://localhost:8000/api/logs` 查看日志

查询参数:
- `level`: 按日志级别过滤(ERROR, WARNING, INFO, DEBUG)
- `start` / `end`: 日期范围(ISO格式)
- `logger_name`: 按日志记录器过滤
- `limit`: 最大结果数(默认100,最大1000)

示例:
```bash
# 查看最近的错误日志
curl "http://localhost:8000/api/logs?level=ERROR&limit=50"

# 查看特定时间范围的日志
curl "http://localhost:8000/api/logs?start=2026-03-17T00:00:00&end=2026-03-17T23:59:59"
```

## ⚡ 性能指标

- API响应时间: 10-50ms(缓存命中), 200-500ms(缓存未命中)
- 数据库查询: 20-50ms(连接池)
- 缓存命中率: 70-90%(典型使用场景)
- 并发支持: 100+用户

## 🧪 测试

运行所有测试:

```bash
./manage.sh test
# 或
python -m pytest tests/ -v
```

真实系统 smoke test:

```bash
BASE_URL=http://127.0.0.1:8000 bash scripts/smoke_test.sh
```

依赖安全扫描:

```bash
python -m pip_audit -r requirements.txt
```

自定义预警通知通道配置（可选）：

- `ALERT_WEBHOOK_URL`：通用 Webhook（Apprise 支持的 URL）
- `ALERT_EMAIL_URL`：邮件通道 URL（Apprise 格式）
- `ALERT_WECHAT_URL`：微信通道 URL（Apprise 格式）
- `ALERT_WEBHOOK_MAX_RETRIES`：Webhook 失败后重试次数（默认 1，总尝试 2 次）
- `ALERT_EMAIL_MAX_RETRIES`：Email 失败后重试次数（默认 2，总尝试 3 次）
- `ALERT_WECHAT_MAX_RETRIES`：WeChat 失败后重试次数（默认 2，总尝试 3 次）
- `ALERT_COOLDOWN_MINUTES`：系统级告警冷却时间

通知策略说明：

- `channels=system`：走本地系统通知（macOS）
- `channels=email/wechat/webhook`：按通道独立发送，失败自动重试，并写入 `notification_delivery_logs` 发送日志表
- 通道未配置时不会中断主流程，但会写入失败日志，便于排查

测试工具和安全扫描工具位于 `requirements-dev.txt`, 不会进入生产运行时依赖。

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

### v2.0.0 (2026-03-17) - 性能与稳定性增强
- ✅ 数据库连接池 - 提升50%查询性能
- ✅ Redis缓存层 - 减少80-90%响应时间
- ✅ Prometheus监控 - 完整的指标收集
- ✅ PostgreSQL日志 - 结构化日志存储
- ✅ 告警系统 - 多渠道智能告警
- ✅ Docker Compose - 一键部署所有服务
- ✅ 85+测试全部通过

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

项目作者与维护者以仓库提交历史为准。
