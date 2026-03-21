from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # 数据采集配置
    collection_interval: int = 30
    data_source_timeout: int = 10
    signal_dedup_window_seconds: int = 1800
    price_regime_break_threshold: float = 0.25
    price_guard_reference_window: int = 120
    price_guard_min_reference_points: int = 5
    price_guard_relative_deviation_threshold: float = 0.2
    sina_symbol: str = "hf_AUTD"
    eastmoney_fs: str = "m:118"
    eastmoney_code: str = "AU9999"
    eastmoney_name: str = "黄金9999"
    sge_symbol: str = "Au99.99"

    # 分析配置
    rsi_period: int = 14
    bollinger_period: int = 20
    bollinger_std: int = 2
    ma_short: int = 7
    ma_medium: int = 30
    ma_long: int = 90
    macd_fast_period: int = 12
    macd_slow_period: int = 26
    macd_signal_period: int = 9

    # 通知配置
    enable_notification: bool = True
    notification_cooldown: int = 24

    # 数据库配置
    database_path: str = "data/gold_price.db"
    backup_enabled: bool = True
    backup_time: str = "02:00"

    # Web 服务配置
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Redis配置
    redis_enabled: bool = True
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    redis_max_connections: int = 50

    # PostgreSQL配置
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "goldprice_logs"
    postgres_user: str = "goldprice"
    postgres_password: str = ""

    # 缓存配置
    cache_price_ttl: int = 120
    cache_indicators_ttl: int = 120
    cache_history_ttl: int = 300
    cache_candlestick_ttl: int = 300
    cache_signals_ttl: int = 120
    cache_analysis_ttl: int = 180

    # 数据库连接池配置
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout: int = 30
    database_pool_recycle: int = 3600

    # 监控配置
    prometheus_enabled: bool = True
    prometheus_port: int = 9090
    metrics_collection_interval: int = 30

    # 告警配置
    alert_webhook_url: Optional[str] = None
    alert_slack_webhook: Optional[str] = None
    alert_cooldown_minutes: int = 30

    # 日志配置
    log_level: str = "INFO"
    log_to_postgres: bool = True
    log_retention_days: int = 30

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
