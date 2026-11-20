#!/usr/bin/env python3
"""Probe script (run by tools/task_lint.py only): the checker's own factor test on the known-false variant
"n*n + 1 is prime for every whole number n >= 1".  python3 variant_check.py CHECKER OBJECT"""
import importlib.util
import json
import sys

spec = importlib.util.spec_from_file_location("checker", sys.argv[1])
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
with open(sys.argv[2], encoding="utf-8") as fh:
    n = json.load(fh)["n"]
value = n * n + 1
factor = checker.smallest_factor(value)
print(json.dumps({"valid": factor is not None, "score": None,
                  "reason": "variant n*n + 1: %d " % value + ("= %d * %d" % (factor, value // factor) if factor else "is prime")}))
