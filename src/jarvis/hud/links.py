"""Opening what the HUD lists: web pages in the browser, files the same safe way as by voice.

Links come from web content (news, search results), so only http(s) addresses are opened;
files open through ``open_path``, which never runs programs or scripts (ADR-031).
"""

import logging
import webbrowser
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from jarvis.tools.base import Link
from jarvis.tools.files import open_path

log = logging.getLogger(__name__)

WEB_SCHEMES = {"http", "https"}


def open_link(
    link: Link,
    browser: Callable[[str], object] = webbrowser.open,
    files: Callable[[Path], object] = open_path,
) -> bool:
    """Open a clicked entry; False when it was refused."""
    if link.kind == "file":
        files(Path(link.target))
        return True
    if urlparse(link.target).scheme.lower() not in WEB_SCHEMES:
        log.warning("Refused to open a link that is not a web page: %r", link.target)
        return False
    browser(link.target)
    return True
