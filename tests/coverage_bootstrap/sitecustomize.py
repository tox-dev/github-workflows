from __future__ import annotations

import os
import sys

if "GW_COVERAGE_SITE_PACKAGES" in os.environ:
    sys.path.append(os.environ["GW_COVERAGE_SITE_PACKAGES"])
    from coverage import process_startup

    process_startup()
