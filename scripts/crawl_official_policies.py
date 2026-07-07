from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from suda_policy_agent.crawler import crawl_official_policies


if __name__ == "__main__":
    print(json.dumps(crawl_official_policies(), ensure_ascii=False, indent=2))
