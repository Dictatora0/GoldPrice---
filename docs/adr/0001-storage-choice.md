# ADR 0001: SQLite for Local Use, PostgreSQL for Production

## 背景
GoldPrice 需要支持个人本地运行和长期运行两种模式。

## 决策
默认保留 SQLite 作为本地单机存储，生产或长期运行建议使用 PostgreSQL。

## 影响
本地启动更简单；生产环境需要显式配置 PostgreSQL，并承担额外运维成本。
