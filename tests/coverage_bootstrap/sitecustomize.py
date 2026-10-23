from __future__ import annotations

import os
import sys
from pathlib import Path

if "GW_PYPI_METADATA_FILE" in os.environ and Path(sys.argv[0]).name == "check_lock_groups.py":
    import json
    from io import BytesIO
    from unittest.mock import patch
    from urllib.parse import urlsplit
    from urllib.request import Request

    _LISTINGS = json.loads(Path(os.environ["GW_PYPI_METADATA_FILE"]).read_text())

    def _pypi_urlopen(request: Request, **_options: float) -> BytesIO:
        url = urlsplit(request.full_url)
        if url.scheme != "https" or url.netloc != "pypi.org" or not url.path.startswith("/simple/"):
            raise ValueError(f"unexpected PyPI metadata request: {request.full_url}")
        name = url.path.removeprefix("/simple/").strip("/")
        return BytesIO(
            json.dumps({"meta": {"api-version": "1.4"}, "name": name, "files": _LISTINGS.get(name, [])}).encode()
        )

    patch("urllib.request.urlopen", _pypi_urlopen).start()

if "GW_COVERAGE_SITE_PACKAGES" in os.environ:
    sys.path.append(os.environ["GW_COVERAGE_SITE_PACKAGES"])
    from coverage import process_startup

    process_startup()
