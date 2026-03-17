import os
import sys
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Ensure settings parse during tests (override any host env)
os.environ["DEBUG"] = "false"
os.environ["ENABLE_NOTIFICATION"] = "false"
os.environ["DATABASE_PATH"] = "/tmp/gold_price_test.db"

# Disable connection pooling for tests to avoid SQLite threading issues
os.environ["DATABASE_POOL_SIZE"] = "0"

@pytest.fixture(scope="function", autouse=True)
def cleanup_database_connections():
    """Clean up database connections after each test"""
    yield
    # Close any open database connections
    try:
        from app.database.pooling import engine
        if engine:
            engine.dispose()
    except Exception:
        pass
