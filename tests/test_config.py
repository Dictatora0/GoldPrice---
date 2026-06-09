import importlib

import pytest
from pydantic import ValidationError


def test_postgres_password_required_for_postgres_logging(monkeypatch):
    monkeypatch.setenv("LOG_TO_POSTGRES", "true")
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    with pytest.raises(ValidationError):
        config_module = importlib.import_module("config")
        config_module = importlib.reload(config_module)
        config_module.Settings(_env_file=None)
