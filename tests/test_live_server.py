from __future__ import annotations

import json
from pathlib import Path
import socket
import sys
import tempfile
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import tomllib
from src.live_server import setup
from src.live_server.extension import LiveServer


class TestLiveServerExtension:
    def test_setup_and_registration(self, mock_api) -> None:
        ext = setup(mock_api)
        assert "live_server" in mock_api.registered_extensions
        assert isinstance(ext, LiveServer)
        assert "live_server.start" in mock_api.commands.commands
        assert "live_server.stop" in mock_api.commands.commands

    def test_extension_manifest_contract(self) -> None:
        manifest_path = Path(__file__).parent.parent / "extension.toml"
        assert manifest_path.exists()
        with open(manifest_path, "rb") as f:
            data = tomllib.load(f)
        assert data["extension"]["id"] == "live_server"
        assert data["extension"]["author"] == "tomlin7"
        assert data["extension"]["version"] == "0.2.0"
        assert data["dependencies"]["python"] == []
        assert data["dependencies"]["tools"] == []

    def test_port_conflict_resolution(self, mock_api) -> None:
        ext = LiveServer(mock_api)
        # Bind a socket on a port to simulate conflict
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as dummy:
            dummy.bind(("127.0.0.1", 0))
            busy_port = dummy.getsockname()[1]

            # find_available_port starting at busy_port should return next port
            open_port = ext.find_available_port(busy_port)
            assert open_port != busy_port
            assert open_port > busy_port

    def test_real_http_server_and_script_injection(self, mock_api) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            index_html = tmppath / "index.html"
            index_html.write_text("<!DOCTYPE html><html><body><h1>Hello World</h1></body></html>", encoding="utf-8")

            ext = LiveServer(mock_api)
            port = ext.start(port=5510, root_dir=str(tmppath))
            try:
                assert ext.is_running is True
                assert ext.server_port == port
                assert f"Port: {port}" in ext.statusbar_button.text

                # Perform actual HTTP GET request over 127.0.0.1
                url = ext.get_url("index.html")
                with urllib.request.urlopen(url, timeout=5) as response:
                    assert response.status == 200
                    content = response.read().decode("utf-8")
                    assert "Hello World" in content
                    assert "live-reload" in content
                    assert "</body>" in content

                # Verify /live-reload-check endpoint
                check_url = ext.get_url("live-reload-check")
                with urllib.request.urlopen(check_url, timeout=5) as resp:
                    assert resp.status == 200
                    data = json.loads(resp.read().decode("utf-8"))
                    assert data["version"] == 1

                # Trigger reload broadcast and verify version increments
                ext.notify_reload()
                with urllib.request.urlopen(check_url, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    assert data["version"] == 2
            finally:
                ext.stop()
                assert ext.is_running is False
                assert ext.statusbar_button.text == "Go Live"

    def test_mime_types_and_directory_listing(self, mock_api) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            css_file = tmppath / "style.css"
            css_file.write_text("body { color: red; }", encoding="utf-8")
            js_file = tmppath / "app.js"
            js_file.write_text("console.log('hi');", encoding="utf-8")

            ext = LiveServer(mock_api)
            port = ext.start(port=5520, root_dir=str(tmppath))
            try:
                # Test CSS MIME type
                with urllib.request.urlopen(ext.get_url("style.css"), timeout=5) as resp:
                    assert resp.status == 200
                    assert "text/css" in resp.headers.get("Content-Type", "")

                # Test JS MIME type
                with urllib.request.urlopen(ext.get_url("app.js"), timeout=5) as resp:
                    assert resp.status == 200
                    assert "javascript" in resp.headers.get("Content-Type", "")

                # Test directory listing (no index.html in tmppath)
                with urllib.request.urlopen(ext.get_url("/"), timeout=5) as resp:
                    assert resp.status == 200
                    body = resp.read().decode("utf-8")
                    assert "Index of" in body
                    assert "style.css" in body
            finally:
                ext.stop()

    def test_404_error_handling(self, mock_api) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ext = LiveServer(mock_api)
            port = ext.start(port=5530, root_dir=str(tmpdir))
            try:
                import urllib.error
                with pytest.raises(urllib.error.HTTPError) as exc_info:
                    urllib.request.urlopen(ext.get_url("missing.txt"), timeout=5)
                assert exc_info.value.code == 404
            finally:
                ext.stop()

    def test_toggle_and_open_browser(self, mock_api) -> None:
        ext = LiveServer(mock_api)
        with patch.object(ext, "start") as mock_start, patch.object(ext, "stop") as mock_stop:
            ext.is_running = False
            ext.toggle()
            mock_start.assert_called_once()

            ext.is_running = True
            ext.toggle()
            mock_stop.assert_called_once()

        with patch("webbrowser.open", return_value=True) as mock_wb:
            ext.server_port = 5500
            assert ext.open_browser("about.html") is True
            mock_wb.assert_called_with("http://127.0.0.1:5500/about.html")

    def test_app_instance_compatibility(self, app_instance) -> None:
        ext = setup(app_instance.api)
        assert ext is not None
