#!/usr/bin/env python3
"""Run a unittest discovery suite and surface failures as GitHub annotations."""

from __future__ import annotations

import argparse
import os
import sys
import unittest
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("start_dir", type=Path)
    return parser.parse_args()


def github_escape(value: str, *, property_value: bool = False) -> str:
    escaped = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if property_value:
        escaped = escaped.replace(":", "%3A").replace(",", "%2C")
    return escaped


class AnnotatingResult(unittest.TextTestResult):
    def _annotate(self, kind: str, test: unittest.case.TestCase, error: Any) -> None:
        if os.environ.get("GITHUB_ACTIONS") != "true":
            return
        title = github_escape(f"{kind}: {test.id()}", property_value=True)
        details = self._exc_info_to_string(error, test)
        print(f"::error title={title}::{github_escape(details)}", file=sys.stderr)

    def addFailure(self, test: unittest.case.TestCase, err: Any) -> None:  # noqa: N802
        super().addFailure(test, err)
        self._annotate("Failure", test, err)

    def addError(self, test: unittest.case.TestCase, err: Any) -> None:  # noqa: N802
        super().addError(test, err)
        self._annotate("Error", test, err)


def main() -> None:
    args = parse_args()
    suite = unittest.defaultTestLoader.discover(str(args.start_dir))
    result = unittest.TextTestRunner(verbosity=2, resultclass=AnnotatingResult).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
