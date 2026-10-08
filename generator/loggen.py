#!/usr/bin/env python3
"""Einstieg: python loggen.py --help"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loggen.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
