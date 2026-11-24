"""Development and packaging entry point.

Use ``python -m smartdrive`` or the ``smartdrive`` console script after installation.
This file exists so PyInstaller has a single top-level script to freeze.
"""

from smartdrive.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
