from __future__ import annotations

import http.server
import json
import mimetypes
import os
from pathlib import Path
import socket
import threading
import typing
from typing import Any
import urllib.parse
import webbrowser

from biscuit.extensions import Extension

if typing.TYPE_CHECKING:
    from biscuit.api import ExtensionsAPI


LIVE_RELOAD_SCRIPT = """
<script>
// Biscuit Live Server Auto-Reload Script
(function() {
    let currentVersion = null;
    function checkReload() {
        fetch('/live-reload-check')
            .then(res => res.json())
            .then(data => {
                if (currentVersion === null) {
                    currentVersion = data.version;
                } else if (data.version !== currentVersion) {
                    console.log('[Live Server] Reloading page due to workspace changes...');
                    window.location.reload();
                }
            })
            .catch(() => {})
            .finally(() => {
                setTimeout(checkReload, 750);
            });
    }
    checkReload();
})();
</script>
"""


class LiveReloadHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Custom HTTP Request Handler serving static workspace files with live reload injection."""

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress standard stderr logging to keep console clean."""
        pass

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # Handle live reload health/version endpoint
        if path == "/live-reload-check":
            version = getattr(self.server, "reload_version", 1)
            payload = json.dumps({"version": version}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(payload)
            return

        # Handle standalone reload client script
        if path == "/live-reload.js":
            script_bytes = LIVE_RELOAD_SCRIPT.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(script_bytes)))
            self.end_headers()
            self.wfile.write(script_bytes)
            return

        # Resolve local file path
        root_dir = Path(getattr(self.server, "root_dir", os.getcwd())).resolve()
        relative_path = path.lstrip("/")
        target_path = (root_dir / relative_path).resolve()

        # Security check: Prevent path traversal outside root directory
        try:
            target_path.relative_to(root_dir)
        except ValueError:
            self.send_error_response(403, "Access Denied")
            return

        # Directory resolution
        if target_path.is_dir():
            index_file = target_path / "index.html"
            if not index_file.exists():
                index_file = target_path / "index.htm"
            if index_file.exists() and index_file.is_file():
                target_path = index_file
            else:
                self.serve_directory_listing(target_path, root_dir)
                return

        # File serving
        if not target_path.exists() or not target_path.is_file():
            self.send_error_response(404, f"File not found: {path}")
            return

        self.serve_file(target_path)

    def serve_file(self, file_path: Path) -> None:
        try:
            content_type, _ = mimetypes.guess_type(str(file_path))
            if content_type is None:
                content_type = "application/octet-stream"

            with open(file_path, "rb") as f:
                raw_bytes = f.read()

            # If HTML, inject live reload script
            if "text/html" in content_type:
                html_text = raw_bytes.decode("utf-8", errors="replace")
                if "</body>" in html_text:
                    html_text = html_text.replace("</body>", f"{LIVE_RELOAD_SCRIPT}\n</body>")
                elif "</html>" in html_text:
                    html_text = html_text.replace("</html>", f"{LIVE_RELOAD_SCRIPT}\n</html>")
                else:
                    html_text += LIVE_RELOAD_SCRIPT
                raw_bytes = html_text.encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw_bytes)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(raw_bytes)
        except Exception as e:
            self.send_error_response(500, f"Internal Server Error: {e}")

    def serve_directory_listing(self, dir_path: Path, root_dir: Path) -> None:
        try:
            items = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            rel = dir_path.relative_to(root_dir).as_posix()
            display_path = "/" if rel == "." else f"/{rel}/"

            links = []
            if dir_path != root_dir:
                links.append('<li><a href="../">../</a></li>')

            for item in items:
                name = item.name + ("/" if item.is_dir() else "")
                links.append(f'<li><a href="{urllib.parse.quote(name)}">{name}</a></li>')

            listing_html = f"""<!DOCTYPE html>
<html>
<head><title>Index of {display_path}</title></head>
<body>
<h1>Index of {display_path}</h1>
<hr>
<ul>{''.join(links)}</ul>
<hr>
{LIVE_RELOAD_SCRIPT}
</body>
</html>"""
            payload = listing_html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            self.send_error_response(500, str(e))

    def send_error_response(self, code: int, message: str) -> None:
        body = f"<html><body><h1>{code} - {message}</h1></body></html>".encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class LiveServer(Extension):
    """Local development server with live reload for static and dynamic web pages."""

    def __init__(self, api: ExtensionsAPI) -> None:
        super().__init__(api)
        self.api = api
        self.server_port = 5500
        self.is_running = False
        self.server: http.server.ThreadingHTTPServer | None = None
        self.server_thread: threading.Thread | None = None
        self.root_dir = os.getcwd()
        self.statusbar_button = None

        if hasattr(self.api, "statusbar") and hasattr(self.api.statusbar, "add_button"):
            try:
                self.statusbar_button = self.api.statusbar.add_button(
                    text="Go Live",
                    icon="radio-tower",
                    callback=self.toggle,
                    description="Click to toggle Live Server",
                )
                if self.statusbar_button:
                    self.statusbar_button.show()
            except Exception as e:
                self.api.logger.warning(f"Live Server statusbar button: {e}")

        self._register_commands()
        self.api.logger.info("Live Server extension loaded successfully.")

    def _register_commands(self) -> None:
        if not hasattr(self.api, "commands"):
            return
        cmds = {
            "live_server.start": self.start,
            "live_server.stop": self.stop,
            "live_server.open_browser": self.open_browser,
            "live_server.reload": self.notify_reload,
        }
        for name, callback in cmds.items():
            self.api.commands.register_command(name, callback)

    def find_available_port(self, start_port: int = 5500, max_attempts: int = 100) -> int:
        """Find an open TCP port starting from start_port."""
        for port in range(start_port, start_port + max_attempts):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    continue
        return start_port

    def start(self, port: int = 5500, root_dir: str | None = None) -> int:
        """Launch background HTTP server with live reload support."""
        if self.is_running and self.server:
            self.api.logger.info(f"Live Server is already running on port {self.server_port}")
            return self.server_port

        if root_dir is not None:
            self.root_dir = str(root_dir)

        allocated_port = self.find_available_port(port)
        self.server_port = allocated_port

        try:
            self.server = http.server.ThreadingHTTPServer(("127.0.0.1", allocated_port), LiveReloadHTTPHandler)
            setattr(self.server, "root_dir", self.root_dir)
            setattr(self.server, "reload_version", 1)

            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            self.is_running = True

            if self.statusbar_button:
                self.statusbar_button.change_text(f"Port: {allocated_port}")

            self.api.logger.info(f"Live Server running at http://127.0.0.1:{allocated_port}/")
            return allocated_port
        except Exception as e:
            self.api.logger.error(f"Failed to start Live Server on port {allocated_port}: {e}")
            self.is_running = False
            return -1

    def stop(self) -> bool:
        """Stop running HTTP server and join thread."""
        if not self.is_running or not self.server:
            return True

        try:
            self.server.shutdown()
            self.server.server_close()
            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=2.0)
            self.server = None
            self.server_thread = None
            self.is_running = False

            if self.statusbar_button:
                self.statusbar_button.change_text("Go Live")

            self.api.logger.info("Live Server stopped.")
            return True
        except Exception as e:
            self.api.logger.error(f"Error stopping Live Server: {e}")
            return False

    def notify_reload(self) -> None:
        """Increment reload version to trigger client page reload."""
        if self.server:
            current = getattr(self.server, "reload_version", 1)
            setattr(self.server, "reload_version", current + 1)
            self.api.logger.info("Live Server reload broadcast sent.")

    def toggle(self) -> None:
        """Toggle server running state."""
        if self.is_running:
            self.stop()
        else:
            self.start(self.server_port)

    def get_url(self, path: str = "") -> str:
        """Format full HTTP URL for a given relative path."""
        clean = path.lstrip("/")
        return f"http://127.0.0.1:{self.server_port}/{clean}"

    def open_browser(self, path: str = "") -> bool:
        """Open default web browser pointing to server."""
        url = self.get_url(path)
        try:
            return webbrowser.open(url)
        except Exception as e:
            self.api.logger.error(f"Failed to open browser: {e}")
            return False

    def install(self) -> None:
        """Run on extension installation."""
        self.api.logger.info("Live Server extension installed.")
