"""
A local HTTP server answering each request with a recorded response, and keeping what it
was sent, standing in for GitHub's REST API.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# %% what the server is told and sent


@dataclass(frozen=True)
class RecordedAnswer:
    """
    What one request is answered with.
    """

    status: HTTPStatus
    """
    The status to answer with.
    """

    body: Path | None = None
    """
    The recorded body to answer with, ``None`` for an empty one.
    """


@dataclass(frozen=True)
class SentRequest:
    """
    One request the server received.
    """

    method: str
    """
    Its HTTP method.
    """

    path: str
    """
    Its path, query included.
    """

    payload: Any
    """
    Its decoded JSON body, ``None`` when it had none.
    """


# %% the server


@dataclass
class ReplayedApi:
    """
    Answers each ``(method, path)`` with the answer recorded for it.
    """

    answers: dict[tuple[str, str], RecordedAnswer]
    """
    The answer to each method and path, query included.
    """

    sent: list[SentRequest] = field(default_factory=list)
    """
    Every request received, in order.
    """

    def __enter__(self) -> ReplayedApi:
        """:return: This server, now answering."""
        replayed = self

        class Handler(BaseHTTPRequestHandler):
            """
            Hands every request to the server's recordings.
            """

            def answer(self) -> None:
                """
                Record the request and send back the recorded answer.
                """
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                replayed.sent.append(
                    SentRequest(
                        self.command, self.path, json.loads(raw) if raw else None
                    )
                )
                recorded = replayed.answers[(self.command, self.path)]
                body = recorded.body.read_bytes() if recorded.body else b""
                self.send_response(recorded.status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = do_PATCH = answer

            def log_message(self, *arguments: Any) -> None:
                """Keep the test output free of request logs."""

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exception: Any) -> None:
        """Stop answering."""
        self.server.shutdown()
        self.server.server_close()

    @property
    def url(self) -> str:
        """:return: Where the server answers, in the form of an API root."""
        host, port = self.server.server_address
        return f"http://{host}:{port}"
