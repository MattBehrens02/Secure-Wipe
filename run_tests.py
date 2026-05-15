#!/usr/bin/env python3
"""Single entry point for running the Secure-Wipe unit test suite."""

import argparse
import sys
import unittest


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Secure-Wipe unit tests")
    parser.add_argument(
        "-k",
        "--pattern",
        default="test*.py",
        help="Glob pattern for test file names (default: test*.py)",
    )
    parser.add_argument(
        "-v",
        "--verbosity",
        type=int,
        default=2,
        choices=[0, 1, 2],
        help="unittest verbosity level (0, 1, 2)",
    )
    args = parser.parse_args()

    loader = unittest.defaultTestLoader
    suite = loader.discover(start_dir="tests", pattern=args.pattern)
    result = unittest.TextTestRunner(verbosity=args.verbosity).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
