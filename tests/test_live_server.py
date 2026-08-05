from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.live_server import setup
from src.live_server.extension import LiveServer


class TestLiveServerExtension:
    def test_extension_setup(self, app_instance) -> None:
        setup(app_instance.api)
        ext = LiveServer(app_instance.api)
        port = ext.start(8080)
        assert port == 8080
        assert ext.is_running is True
        assert ext.get_url("index.html") == "http://127.0.0.1:8080/index.html"
        ext.stop()
        assert ext.is_running is False
