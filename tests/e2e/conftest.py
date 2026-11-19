import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn

from app.main import app, reset_store


@pytest.fixture(scope="session")
def live_server() -> Iterator[str]:
    """Run the app with uvicorn on an ephemeral port in a background thread."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
    sock.close()


@pytest.fixture(scope="session")
def base_url(live_server: str) -> str:
    """Point pytest-playwright's relative page.goto() calls at the live server."""
    return live_server


@pytest.fixture(autouse=True)
def clean_store() -> Iterator[None]:
    reset_store()
    yield
    reset_store()
