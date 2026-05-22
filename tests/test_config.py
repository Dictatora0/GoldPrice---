import importlib

import pytest
from pydantic import ValidationError


def test_postgres_password_required_for_postgres_logging(monkeypatch):
    monkeypatch.setenv("LOG_TO_POSTGRES", "true")
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    with pytest.raises(ValidationError):
        import config
        importlib.reload(config)
