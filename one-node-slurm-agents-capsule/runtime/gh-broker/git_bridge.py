"""Streaming Smart HTTP push bridge; GitHub credentials stay in the broker."""

import base64
import http.client
import re
import socket
import socketserver
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

TIMEOUT = 300
MAX_BODY = 2 * 1024**3
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def repo_name(value):
    value = value.removesuffix(".git")
    if not REPO.fullmatch(value) or any(
        part in (".", "..") for part in value.split("/")
    ):
        raise ValueError("Git push target must be a GitHub OWNER/REPO")
    return value


def request_target(path, method):
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise ValueError("Only relative Smart HTTP paths are accepted")
    match = re.fullmatch(r"/([^/]+/[^/]+)/(info/refs|git-receive-pack)", parsed.path)
    if not match:
        raise ValueError("Only Git receive-pack endpoints are allowed")
    repo = repo_name(match[1])
    if (method, match[2], parsed.query) not in (
        ("GET", "info/refs", "service=git-receive-pack"),
        ("POST", "git-receive-pack", ""),
    ):
        raise ValueError("Only Git push is supported by this transport")
    return repo, f"/{repo}.git/{match[2]}" + (
        "?" + parsed.query if parsed.query else ""
    )


def copy_request(source, destination, headers):
    """Relay fixed-length or chunked packs with bounded memory and duration."""
    length = headers.get("Content-Length")
    chunked = headers.get("Transfer-Encoding", "").lower()
    if chunked and (chunked != "chunked" or length is not None):
        raise ValueError("Invalid Git request framing")
    remaining = int(length or 0)
    if not 0 <= remaining <= MAX_BODY:
        raise ValueError("Git push exceeds the 2 GiB transport limit")
    deadline, total = time.monotonic() + TIMEOUT, 0

    def transfer(count):
        while count:
            if time.monotonic() >= deadline:
                raise TimeoutError("Git request timed out")
            data = source.read(min(count, 65536))
            if not data:
                raise ValueError("Incomplete Git request body")
            destination.send(data)
            count -= len(data)

    if not chunked:
        transfer(remaining)
        return
    while True:
        line = source.readline(128)
        if not line.endswith(b"\r\n"):
            raise ValueError("Invalid Git chunk header")
        size = int(line.split(b";", 1)[0].strip(), 16)
        total += size
        if size < 0 or total > MAX_BODY:
            raise ValueError("Git push exceeds the 2 GiB transport limit")
        if not size:
            # Git does not need trailers; reject them instead of forwarding headers.
            if source.readline(4) != b"\r\n":
                raise ValueError("Git request trailers are not supported")
            destination.send(b"0\r\n\r\n")
            return
        destination.send(f"{size:x}\r\n".encode())
        transfer(size)
        if source.read(2) != b"\r\n":
            raise ValueError("Invalid Git chunk boundary")
        destination.send(b"\r\n")


def relay(handler, connection, path, authorization=None):
    """Forward only Git protocol headers, never client credentials or redirects."""
    handler.connection.settimeout(TIMEOUT)
    connection.putrequest(handler.command, path)
    for name in ("Content-Type", "Content-Length", "Transfer-Encoding", "Git-Protocol"):
        if handler.headers.get(name) is not None:
            connection.putheader(name, handler.headers[name])
    connection.putheader("User-Agent", "agentrun-git")
    if authorization:
        connection.putheader("Authorization", authorization)
    connection.endheaders()
    copy_request(handler.rfile, connection, handler.headers)
    response = connection.getresponse()
    handler.send_response(response.status)
    for name in ("Content-Type", "Content-Length", "Cache-Control", "WWW-Authenticate"):
        if response.getheader(name) is not None:
            handler.send_header(name, response.getheader(name))
    handler.send_header("Connection", "close")
    handler.end_headers()
    handler.close_connection = True
    while data := response.read(65536):
        handler.wfile.write(data)
    return response.status


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=TIMEOUT + 10)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class GitHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.forward()

    def do_POST(self):
        self.forward()

    def forward(self):
        try:
            repo, path = request_target(self.path, self.command)
        except ValueError as error:
            self.send_error(400, str(error))
            return
        try:
            reason = self.server.check_repo(repo)
            if reason:
                self.server.log(f"denied git push to {repo}")
                self.send_error(403, reason.replace(self.server.token(), "***"))
                return
            if (
                self.command == "POST"
                and self.headers.get("Content-Type")
                != "application/x-git-receive-pack-request"
            ):
                raise ValueError("Invalid Git receive-pack content type")
            encoded = base64.b64encode(
                ("x-access-token:" + self.server.token()).encode()
            ).decode()
            with closing(self.server.upstream()) as connection:
                status = relay(self, connection, path, "Basic " + encoded)
            self.server.log(f"git push HTTP {self.command} {path} -> {status}")
        except (OSError, ValueError, http.client.HTTPException):
            self.server.log("git push HTTP transport failed")
            self.send_error(502, "Git push transport failed; see the broker log")


class GitServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self, path, check_repo, token, log, upstream=None):
        self.check_repo, self.token, self.log = check_repo, token, log
        self.upstream = upstream or (
            lambda: http.client.HTTPSConnection("github.com", timeout=TIMEOUT)
        )
        super().__init__(path, GitHandler)
