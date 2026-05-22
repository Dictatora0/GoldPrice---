# ADR 0003: Sensitive Configuration via Environment Variables

## 背景
密码、API key 和连接信息不能硬编码进仓库或镜像。

## 决策
所有敏感配置从环境变量注入，缺失时在启动或初始化阶段报错。

## 影响
部署必须提供显式配置；但可以避免弱默认值和密钥泄漏。
