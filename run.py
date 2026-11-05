"""Run with Python 3.11+; .deps is an optional project-local dependency directory."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent / '.deps'))
from madrasflow.cli import main

if __name__ == '__main__':
    main()
