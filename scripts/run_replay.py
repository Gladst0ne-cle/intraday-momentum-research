"""Repository-root entry point; independent of the working directory."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from replay_cli import main

if __name__ == '__main__':
    main()
