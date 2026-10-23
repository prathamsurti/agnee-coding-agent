import sys
from pathlib import Path

# Ensure packages/shared-protocol is in sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
shared_protocol_path = root_dir / "packages" / "shared-protocol"
if shared_protocol_path.exists() and str(shared_protocol_path) not in sys.path:
    sys.path.insert(0, str(shared_protocol_path))
