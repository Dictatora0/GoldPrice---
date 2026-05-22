# ADR 0002: Unified Cache Key Namespace

## 背景
缓存 key 分散定义会增加误删、冲突和排查成本。

## 决策
统一使用 `gold:` 作为缓存命名空间，并通过集中 helper 生成 key。

## 影响
缓存失效更安全，模块之间更容易保持一致，但需要少量兼容别名。
