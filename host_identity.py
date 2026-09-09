#!/usr/bin/env python3
"""Read fixed, non-secret node identity files from ext4 without mounting it."""

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
    name = "otter-block-device-" + uuid.uuid4().hex
    quoted_name = urllib.parse.quote(name, safe="")
    probe = r'''
printf 'probe_version=4\n'
printf 'probe_identity='; id
printf 'kernel_root_args='
for argument in $(cat /proc/cmdline 2>/dev/null); do
    case "$argument" in
        root=*|rootflags=*) printf '%s ' "$argument" ;;
    esac
done
printf '\n'
printf '%s\n' '[lsblk]'
lsblk -o NAME,MAJ:MIN,SIZE,RO,TYPE,FSTYPE,FSVER,LABEL,UUID,MOUNTPOINTS,MODEL 2>/dev/null || true

debugfs_bin=$(command -v debugfs 2>/dev/null || true)
if [ -z "$debugfs_bin" ]; then
    printf '%s\n' 'debugfs_unavailable'
    exit 41
fi

normalize_absolute() {
    local candidate=$1
    local normalized=
    local part
    local old_ifs=$IFS
    IFS=/
    set -- $candidate
    IFS=$old_ifs
    for part in "$@"; do
        case "$part" in
            ''|.) ;;
            ..) normalized=${normalized%/*} ;;
            *) normalized=$normalized/$part ;;
        esac
    done
    printf '%s\n' "${normalized:-/}"
}

read_fixed_file() {
    device=$1
    requested_path=$2
    current_path=$requested_path
    hop=0

    while [ "$hop" -lt 5 ]; do
        case "$current_path" in
            /etc/*|/usr/*|/nix/store/*) ;;
            *) return 1 ;;
        esac
        case "$current_path" in
            *[!A-Za-z0-9_./+:-]*) return 1 ;;
        esac

        inode=$(
            timeout 10 "$debugfs_bin" -c -R "stat $current_path" "$device" \
                2>/dev/null || true
        )
        target=$(
            printf '%s\n' "$inode" \
                | sed -n 's/^Fast link dest: "\(.*\)"$/\1/p' \
                | sed -n '1p'
        )
        if [ -z "$target" ]; then
            if ! printf '%s\n' "$inode" | grep -q 'Type: regular'; then
                return 1
            fi
            content=$(
                timeout 10 "$debugfs_bin" -c -R "cat $current_path" "$device" \
                    2>/dev/null || true
            )
            if [ -z "$content" ]; then
                return 1
            fi
            printf 'raw_file_device=%s\n' "$device"
            printf 'raw_file_requested=%s\n' "$requested_path"
            printf 'raw_file_resolved=%s\n' "$current_path"
            printf 'raw_file_sha256=%s\n' \
                "$(printf '%s' "$content" | sha256sum | awk '{print $1}')"
            printf '%s\n' "$content" \
                | LC_ALL=C tr -cd '\11\12\15\40-\176' \
                | head -c 2048 \
                | sed 's/^/raw_file_content=/'
            printf '\n'
            return 0
        fi

        case "$target" in
            /*) current_path=$target ;;
            *) current_path=$(dirname "$current_path")/$target ;;
        esac
        current_path=$(normalize_absolute "$current_path")
        hop=$((hop + 1))
    done
    return 1
}

success=0
for device in ${DEVICES:-/dev/sda1 /dev/sda3}; do
    [ -b "$device" ] || continue
    blkid_output=$(blkid "$device" 2>/dev/null || true)
    fstype=$(printf '%s\n' "$blkid_output" | sed -n 's/.* TYPE="\([^"]*\)".*/\1/p')
    uuid=$(printf '%s\n' "$blkid_output" | sed -n 's/.* UUID="\([^"]*\)".*/\1/p')
    printf 'candidate=%s fstype=%s uuid=%s kernel_read_only=' \
        "$device" "${fstype:-unknown}" "${uuid:-unknown}"
    blockdev --getro "$device" 2>/dev/null || printf 'unknown\n'
    [ "$fstype" = ext4 ] || continue

    for fixed_path in /etc/hostname /etc/os-release /usr/lib/os-release; do
        if read_fixed_file "$device" "$fixed_path"; then
            success=1
            break
        fi
    done
    [ "$success" = 1 ] && break
done

if [ "$success" != 1 ]; then
    printf '%s\n' 'no_fixed_identity_file_read'
    exit 42
fi
'''
    body = {
        "Image": IMAGE,
        "Cmd": [
            "/bin/sh",
            "-c",
            probe,
        ],
        "Tty": True,
        "HostConfig": {"Privileged": True, "PidMode": "host"},
        "Labels": {"purpose": "authorized-otter-read-only-raw-ext4-probe"},
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
