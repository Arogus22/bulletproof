#!/usr/bin/env python3
"""Explicit platform entry point for shared workflow scripts."""
import argparse
import os
import runpy
import sys
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--platform", choices=("claude", "codex"), required=True)
p.add_argument("workflow", choices=("framework-init", "testar"))
args, remaining = p.parse_known_args()
os.environ["BULLETPROOF_PLATFORM"] = args.platform
script = Path(__file__).with_name(args.workflow + ".py")
sys.argv = [str(script)] + remaining
runpy.run_path(str(script), run_name="__main__")
