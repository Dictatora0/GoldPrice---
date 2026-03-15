import argparse
import os

from app.database import init_db
from app.main import create_app
from app.port_manager import PortManager
from config import settings


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="GoldPrice Service")
    parser.add_argument("--init-db", action="store_true", help="Initialize database")
    parser.add_argument("--port", type=int, help="HTTP port")
    parser.add_argument("--interval", type=int, help="Collection interval in minutes")
    parser.add_argument("--no-notify", action="store_true", help="Disable notifications")
    return parser.parse_args(argv)


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

    app = create_app()
    manager = PortManager(project_root=os.path.dirname(__file__), host="127.0.0.1")
    manager.start_server(app, port=settings.port, start=8001, end=8100)


if __name__ == "__main__":
    main()
