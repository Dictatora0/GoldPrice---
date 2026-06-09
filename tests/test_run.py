from config import Settings
from run import parse_args


def test_parse_args_overrides():
    args = parse_args(["--port", "9000", "--interval", "30", "--no-notify"])

    assert args.port == 9000
    assert args.interval == 30
    assert args.no_notify is True


def test_parse_args_supports_cleanup_backfill():
    args = parse_args(
        [
            "--cleanup-backfill",
            "--created-after",
            "2026-03-20T20:22:50",
            "--created-before",
            "2026-03-20T20:22:53",
            "--dry-run",
        ]
    )

    assert args.cleanup_backfill is True
    assert args.created_after == "2026-03-20T20:22:50"
    assert args.created_before == "2026-03-20T20:22:53"
    assert args.dry_run is True


def test_collection_interval_default_is_30_seconds():
    assert Settings(_env_file=None).collection_interval == 30
