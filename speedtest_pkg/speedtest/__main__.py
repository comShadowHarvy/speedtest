import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, "..", ".."))

from speedtest_pkg.speedtest.cli import run_benchmark

if __name__ == "__main__":
    sys.exit(run_benchmark())
