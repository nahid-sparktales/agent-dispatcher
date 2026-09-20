#!/bin/bash
# Manual Claude install/update or --uninstall. Builds and validates before staging a
# recoverable transaction. The optional decision engine remains inert until enabled.
set -euo pipefail
exec python3 "$(dirname "$0")/install_claude.py" "$@"
