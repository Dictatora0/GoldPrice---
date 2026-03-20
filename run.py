import argparse
import os
from datetime import datetime

from app.database import init_db
from app.scheduler import cleanup_backfill_batch
from config import settings


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="GoldPrice Service")
    parser.add_argument("--init-db", action="store_true", help="Initialize database")
    parser.add_argument(
        "--cleanup-backfill",
        action="store_true",
        help="Clean orphan backfill history and malformed signals in a created_at window",
    )
    parser.add_argument(
        "--created-after",
        help="Inclusive lower bound for created_at window (ISO datetime)",
    )
    parser.add_argument(
        "--created-before",
        help="Inclusive upper bound for created_at window (ISO datetime)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview cleanup-backfill deletions without modifying the database",
    )
    parser.add_argument("--port", type=int, help="HTTP port")
    parser.add_argument("--interval", type=int, help="Collection interval in seconds")
    parser.add_argument("--no-notify", action="store_true", help="Disable notifications")
    args = parser.parse_args(argv)

    if args.cleanup_backfill:
        if not args.created_after or not args.created_before:
            parser.error("--cleanup-backfill requires --created-after and --created-before")
    elif args.created_after or args.created_before or args.dry_run:
        parser.error("--created-after/--created-before/--dry-run require --cleanup-backfill")

    return args


def main():
    args = parse_args()

    if args.interval:
        settings.collection_interval = args.interval
    if args.port:
        settings.port = args.port
    if args.no_notify:
        settings.enable_notification = False

    if args.init_db:
        init_db()
        return

    if args.cleanup_backfill:
        created_after = datetime.fromisoformat(args.created_after)
        created_before = datetime.fromisoformat(args.created_before)
        if created_after > created_before:
            raise ValueError("--created-after must be earlier than or equal to --created-before")

        result = cleanup_backfill_batch(
            created_after=created_after,
            created_before=created_before,
            dry_run=args.dry_run,
        )
        print(result)
        return

    from app.main import create_app
    from app.port_manager import PortManager

    app = create_app()
    manager = PortManager(project_root=os.path.dirname(__file__), host="127.0.0.1")
    manager.start_server(app, port=settings.port, start=8001, end=8100)


if __name__ == "__main__":
    main()
