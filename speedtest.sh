#!/usr/bin/env bash
""":"
# Network Speed Benchmark Tool Launcher
# Enables universal execution via: bash speedtest.sh, sh speedtest.sh, ./speedtest.sh, python3 speedtest.sh
# The actual code lives in speedtest_pkg/speedtest/ as a Python package.
exec python3 "$0" "$@"
"""
# Python docstring (empty, start of Python code)
# -*- coding: utf-8 -*-
"""
# The actual code is in speedtest_pkg/speedtest/ as a Python package.
# This file provides the universal shell execution wrapper.
"""
import os
import sys

# Add package directory to sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, "speedtest_pkg"))

# Re-export the full public API so `import speedtest.sh`-style loaders
# (e.g. tests/test_benchmark.py) keep resolving speedtest.<name>.
from speedtest_pkg.speedtest.core import *  # noqa: F401,F403
from speedtest_pkg.speedtest.core import (  # noqa: F401
    C,
    Spinner,
    VERSION,
    MAX_RETRIES,
    BASE_RETRY_DELAY,
    MAX_RETRY_DELAY,
    HTTP_TIMEOUT,
    DOWNLOAD_TIMEOUT,
    CHECK_TIMEOUT,
    DNS_TIMEOUT,
    DEFAULT_WORKERS,
    HISTORY_FILE,
    MAX_HISTORY_ENTRIES,
    MAX_RUNS,
    MAX_MONITOR_MINUTES,
    MAX_CONSECUTIVE_MONITOR_FAILURES,
    DNS_RESOLVERS,
    IPV6_DNS_RESOLVERS,
    DNS_PROVIDER_DETAILS,
    DNS_QUERIES,
    USER_AGENT,
    JS_PATH_PATTERN,
    TOKEN_PATTERN,
    SPARKLINE_CHARS,
    SITE_TIMING_TARGETS,
    SITE_TIMING_WORKERS,
    SITE_TIMING_RUNS,
    TRACEROUTE_DEFAULT_MAX_HOPS,
    TRACEROUTE_MAX_HOPS,
    TRACEROUTE_DEFAULT_HOSTS,
)
from speedtest_pkg.speedtest.dns import *  # noqa: F401,F403
from speedtest_pkg.speedtest.ui import *  # noqa: F401,F403
from speedtest_pkg.speedtest.network import *  # noqa: F401,F403
from speedtest_pkg.speedtest.engines import *  # noqa: F401,F403
from speedtest_pkg.speedtest.timing import *  # noqa: F401,F403
from speedtest_pkg.speedtest.history import *  # noqa: F401,F403
from speedtest_pkg.speedtest.reports import *  # noqa: F401,F403
from speedtest_pkg.speedtest.cli import *  # noqa: F401,F403
from speedtest_pkg.speedtest.cli import (  # noqa: F401
    run_benchmark,
    run_benchmark_cycle,
    run_single_benchmark,
    validate_args,
)


def _main() -> int:
    return run_benchmark()


if __name__ == "__main__":
    sys.exit(_main())

