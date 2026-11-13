"""Direct execution module entry point: python -m cert_radar."""

import sys
from cert_radar.cli import main

if __name__ == "__main__":
    sys.exit(main())
