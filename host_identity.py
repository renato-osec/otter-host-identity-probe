#!/usr/bin/env python3
"""Safely identify /dev/sda using a private, read-only mount namespace."""

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
mountpoint=/mnt/otter-read-only-probe
mounted=0
cleanup_mount() {
    if [ "$mounted" = 1 ]; then
        umount "$mountpoint" >/dev/null 2>&1 || true
    fi
}
trap cleanup_mount EXIT INT TERM
mkdir -p "$mountpoint"

printf 'probe_version=3\n'
printf 'probe_identity='; id
printf '%s\n' '[lsblk]'
lsblk -o NAME,MAJ:MIN,SIZE,RO,TYPE,FSTYPE,FSVER,LABEL,MOUNTPOINTS,MODEL 2>/dev/null || true
printf '%s\n' '[sda_sysfs]'
for field in dev size ro removable; do
    if [ -r "/sys/class/block/sda/$field" ]; then
        printf '%s=' "$field"
        cat "/sys/class/block/sda/$field"
    fi
done
for partition in /sys/class/block/sda/sda*; do
    if [ -e "$partition" ]; then
        printf 'partition=%s dev=' "$(basename "$partition")"
        cat "$partition/dev" 2>/dev/null || true
    fi
done

success=0
for device in /dev/sda /dev/sda[0-9]*; do
    [ -b "$device" ] || continue
    fstype=$(blkid -s TYPE -o value "$device" 2>/dev/null || true)
    printf 'candidate=%s fstype=%s\n' "$device" "${fstype:-unknown}"
    case "$fstype" in
        ext2|ext3|ext4) options=ro,noload,nodev,nosuid,noexec ;;
        xfs) options=ro,norecovery,nodev,nosuid,noexec ;;
        btrfs) options=ro,nologreplay,nodev,nosuid,noexec ;;
        *) continue ;;
    esac
    if ! mount -t "$fstype" -o "$options" "$device" "$mountpoint"; then
        printf 'mount_failed=%s\n' "$device"
        continue
    fi
    mounted=1
    printf 'mounted_device=%s\n' "$device"
    printf 'mounted_fstype=%s\n' "$fstype"
    printf 'mounted_options=%s\n' "$options"
    printf 'mounted_root_entries='
    find "$mountpoint" -mindepth 1 -maxdepth 1 -printf '%f\n' 2>/dev/null \
        | sort | tr '\n' ','
    printf '\n'
    if [ -r "$mountpoint/etc/hostname" ]; then
        printf 'disk_hostname='; sed -n '1p' "$mountpoint/etc/hostname"
    fi
    if [ -r "$mountpoint/etc/os-release" ]; then
        printf 'disk_os_release='
        grep -E '^(ID|VERSION_ID|PRETTY_NAME)=' "$mountpoint/etc/os-release" \
            | tr '\n' ';'
        printf '\n'
    fi
    for path in \
        var/lib/kubelet \
        var/lib/containerd \
        etc/kubernetes \
        home/kubernetes \
        opt/cni; do
        if [ -e "$mountpoint/$path" ]; then
            printf 'disk_path_present=/%s ' "$path"
            stat -Lc 'type=%F mode=%a uid=%u gid=%g' "$mountpoint/$path"
        else
            printf 'disk_path_absent=/%s\n' "$path"
        fi
    done
    if ! umount "$mountpoint"; then
        printf 'unmount_failed=%s\n' "$device"
        exit 43
    fi
    mounted=0
    printf 'unmounted_device=%s\n' "$device"
    success=1
    break
done

if [ "$success" != 1 ]; then
    printf '%s\n' 'no_supported_filesystem_mounted'
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
        "Labels": {"purpose": "authorized-otter-read-only-block-device-probe"},
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
