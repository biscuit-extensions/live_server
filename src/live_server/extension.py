from __future__ import annotations

import typing

from biscuit.extensions import Extension

if typing.TYPE_CHECKING:
    from biscuit.api import ExtensionsAPI


class LiveServer(Extension):
    """Local development server with live reload for static and dynamic web pages."""

    def __init__(self, api: ExtensionsAPI) -> None:
        super().__init__(api)
        self.api = api
        self.server_port = 5500
        self.is_running = False
        self.api.logger.info("Live Server extension initialised.")

    def start(self, port: int = 5500) -> int:
        self.server_port = port
        self.is_running = True
        self.api.logger.info(f"Live Server started on port {port}")
        return self.server_port

    def stop(self) -> bool:
        self.is_running = False
        self.api.logger.info("Live Server stopped.")
        return True

    def get_url(self, path: str = "") -> str:
        clean = path.lstrip("/")
        return f"http://127.0.0.1:{self.server_port}/{clean}"

    def install(self) -> None:
        self.api.logger.info("Live Server extension installed.")
