from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # 数据采集配置
    collection_interval: int = 3
    data_source_timeout: int = 10
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

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
