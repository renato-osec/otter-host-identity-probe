# Authorized host-identity probe

This payload is for the authorized OtterSec infrastructure test. During Rust
proc-macro expansion it uses the exposed Docker socket to create exactly one
short-lived sibling and enters Docker-daemon PID 1's namespaces.

The first revision ran only:

```sh
whoami
hostname
```

The current revision additionally reports non-secret boundary metadata: PID 1
command, kernel and OS identity, cgroups, namespace IDs, capability and sandbox
flags, selected mount metadata, and presence/permissions of runtime sockets and
Kubernetes service-account files. It reads the namespace name but never reads
the service-account token.

It captures output through Docker logs and deletes the sibling. It does not
mount or modify the host filesystem, read application files or secrets, access
block devices, contact cloud metadata, or call the Kubernetes API.

The block-device revision uses a fresh sibling's private mount namespace to
identify `/dev/sda` and its partitions. For recognized filesystems it mounts
one candidate with read-only, no-journal-replay, `nodev`, `nosuid`, and `noexec`
options. It reads only `/etc/hostname`, `/etc/os-release`, root directory names,
and presence metadata for Kubernetes/containerd directories, then unmounts.
It never enters the Docker-daemon mount namespace for this operation.
