import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Ensure settings parse during tests (override any host env)
os.environ["DEBUG"] = "false"
os.environ["ENABLE_NOTIFICATION"] = "false"
os.environ["DATABASE_PATH"] = "/tmp/gold_price_test.db"
