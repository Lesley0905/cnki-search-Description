#!/usr/bin/env python3
"""
CNKI Search — One-file launcher for OpenClaw Skill & Claude Code.
Usage:
  python cnki_search_cli.py "玉米病害 YOLO" --core-only
  python cnki_search_cli.py --batch queries.json
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cnki_search import main
main()
