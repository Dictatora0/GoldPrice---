from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GITIGNORE = ROOT / ".gitignore"
MANAGE_SH = ROOT / "manage.sh"


def test_gitignore_exists_and_covers_generated_artifacts():
    assert GITIGNORE.exists(), ".gitignore should exist"
    content = GITIGNORE.read_text(encoding="utf-8")

    assert "__pycache__/" in content
    assert "*.py[cod]" in content
    assert ".pytest_cache/" in content
    assert ".ruff_cache/" in content
    assert ".venv*/" in content
    assert "logs/*.log" in content
    assert "logs/*.out" in content
    assert "logs/*.pid" in content
    assert "data/*.db" in content
    assert "data/backups/" in content


def test_manage_script_has_enhanced_usage_and_operational_commands():
    content = MANAGE_SH.read_text(encoding="utf-8")

    assert "Usage: $0 <command>" in content
    assert "doctor" in content
    assert "daemon-check" in content
    assert "config" in content
    assert "cleanup-backfill" in content
    assert "--created-after" in content
    assert "--created-before" in content
    assert "Examples:" in content
    assert "Tips:" in content


def test_manage_script_has_structured_logs_and_preflight_checks():
    content = MANAGE_SH.read_text(encoding="utf-8")

    assert "log_info()" in content
    assert "log_warn()" in content
    assert "log_error()" in content
    assert "ensure_runtime_prerequisites" in content
    assert "detect_pid_by_port" in content
    assert "wait_for_healthy_startup" in content
    assert "startup_payload_ready" in content
    assert "HEALTHCHECK_TIMEOUT_SECONDS" in content


def test_manage_script_routes_cleanup_backfill_command():
    content = MANAGE_SH.read_text(encoding="utf-8")

    assert "run_cleanup_backfill()" in content
    assert "cleanup-backfill)" in content
