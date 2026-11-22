# SPDX-License-Identifier: 0BSD
"""Optional private VoIP wake service. No audio, passwords or mailbox access."""

import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
import uuid
from http.server import BaseHTTPRequestHandler

from call_provider import CallProvider
from family_call_wake import hex_value
from provider import APNs, ProviderHTTPServer, Unavailable


class VoIPAPNs(APNs):
    def __call__(self, token, payload):
        if not hex_value(token, len(token) // 2) or not 32 <= len(token) <= 512:
            raise ValueError("Invalid VoIP token")
        if (
            type(payload) is not dict
            or payload.keys() != {"aps", "next_call"}
            or payload["aps"] != {}
        ):
            raise ValueError("Expected a sealed call payload")
        content = json.dumps(payload, separators=(",", ":"))
        if len(content.encode()) > 5120:
            raise ValueError("VoIP payload exceeds Apple's limit")
        # CallKit must report a genuine incoming call, not a message alert.
        # Expiration zero requests immediate delivery, without offline queuing.
        headers = [
            f"authorization: bearer {self.authorization(int(time.time()))}",
            f"apns-topic: {self.topic}.voip",
            "apns-push-type: voip",
            "apns-priority: 10",
            "apns-expiration: 0",
            f"apns-id: {uuid.uuid4()}",
            "content-type: application/json",
        ]
        config = "\n".join(
            [
                f"url = {json.dumps(f'https://{self.host}/3/device/{token}')}",
                *(f"header = {json.dumps(header)}" for header in headers),
                f"data = {json.dumps(content)}",
            ]
        )
        try:
            result = subprocess.run(
                [
                    "curl",
                    "-q",
                    "--http2",
                    "--noproxy",
                    "*",
                    "--silent",
                    "--max-time",
                    "8",
                    "--output",
                    "/dev/null",
                    "--write-out",
                    "%{http_code}",
                    "--config",
                    "-",
                ],
                input=config,
                capture_output=True,
                timeout=10,
                text=True,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise Unavailable("VoIP transport failed") from error
        if result.stdout != "200":
            raise Unavailable("APNs rejected the call wake")


class CallHandler(BaseHTTPRequestHandler):
    timeout = 5

    def log_message(self, *_):
        pass  # No source IP, token, routing address or signed call log.

    def do_POST(self):
        limits = {
            "/v1/call-subscription": 12000,
            "/v1/call-alert": 2048,
            "/v1/call-cancel": 2048,
            "/v1/call-state": 256,
        }
        status, response = 404, None
        if self.path in limits:
            try:
                # Request smuggling/streaming is not supported by this small service.
                if (
                    self.headers.get("Transfer-Encoding")
                    or len(self.headers.get_all("Content-Length", [])) != 1
                ):
                    raise ValueError("Expected a single fixed-length request")
                length = int(self.headers["Content-Length"])
                if not 0 < length <= limits[self.path]:
                    raise ValueError("Invalid request length")
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError("Incomplete request")
                body = json.loads(raw)
                authorization = self.headers.get("Authorization", "")
                provider = self.server.provider
                if self.path == "/v1/call-subscription":
                    status = provider.register(body, authorization)
                elif self.path == "/v1/call-alert":
                    status = provider.notify(body)
                elif self.path == "/v1/call-cancel":
                    status = provider.cancel(body)
                elif type(body) is dict and body.keys() == {"owner", "call"}:
                    status, response = provider.lookup(
                        body["owner"], body["call"], authorization
                    )
                else:
                    status = 400
            except (OSError, ValueError, RecursionError):
                status = 400
            except sqlite3.Error:
                status = 503
        raw = (
            json.dumps(response, separators=(",", ":")).encode()
            if response is not None
            else b""
        )
        self.send_response(status)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        if raw:
            self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)


def load_config(path):
    path = Path(path)
    if path.stat().st_mode & 0o077:
        raise ValueError("Call configuration must be private")
    config = json.loads(path.read_text())
    if type(config.get("subscriptions")) is not dict:
        raise ValueError("Expected explicit call subscriptions")
    for owner, value in config["subscriptions"].items():
        if (
            not hex_value(owner, 16)
            or type(value) is not dict
            or value.get("allow_calls") is not True
            or not hex_value(value.get("enrollment_hash"), 32)
        ):
            raise ValueError(
                "Every call subscription needs its own explicit authorization"
            )
    apns = config["apns"]
    if (
        not re.fullmatch(r"[A-Za-z0-9.-]+", apns["topic"])
        or apns["topic"].endswith(".voip")
        or not re.fullmatch(r"[A-Z0-9]{10}", apns["team"])
        or not re.fullmatch(r"[A-Z0-9]{10}", apns["key_id"])
    ):
        raise ValueError("Invalid fixed Apple application identity")
    if Path(apns["key_file"]).stat().st_mode & 0o077:
        raise ValueError("The APNs private key must be private")
    database = Path(config["database"])
    if not database.parent.is_dir() or database.parent.stat().st_mode & 0o077:
        raise ValueError("The call database parent must be private")
    if database.exists() and database.stat().st_mode & 0o077:
        raise ValueError("The call database must be private")
    port = config.get("port", 8088)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Invalid loopback port")
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    os.umask(0o077)
    provider = CallProvider(
        config["audience"],
        config["subscriptions"],
        config["database"],
        VoIPAPNs(config["apns"]),
    )
    try:
        with ProviderHTTPServer(
            ("127.0.0.1", config.get("port", 8088)), CallHandler
        ) as server:
            server.provider = provider
            server.serve_forever()
    finally:
        provider.database.close()


if __name__ == "__main__":
    main()
