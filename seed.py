import os
import sys

# Add paths to sys.path
sys.path.insert(0, os.path.abspath("apps/api-gateway"))
sys.path.insert(0, os.path.abspath("packages/shared-protocol"))

import asyncio
from api_gateway.seed import seed_database

if __name__ == "__main__":
    asyncio.run(seed_database())
