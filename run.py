"""Run with Python 3.11+; .deps is an optional project-local dependency directory."""
from pathlib import Path
import sys

deps=Path(__file__).parent / '.deps'
abi=deps/'python_abi.txt'
if abi.exists() and abi.read_text().strip()==f'{sys.version_info.major}.{sys.version_info.minor}':
    sys.path.insert(0,str(deps))
from madrasflow.cli import main

if __name__ == '__main__':
    main()
