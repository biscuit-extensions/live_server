from __future__ import annotations

import typing

from .extension import LiveServer

if typing.TYPE_CHECKING:
    from biscuit.api import ExtensionsAPI


def setup(api: ExtensionsAPI) -> LiveServer:
    """Entrypoint for Biscuit to load the extension."""
    ext = LiveServer(api)
    api.register("live_server", ext)
    ext.install()
    return ext
