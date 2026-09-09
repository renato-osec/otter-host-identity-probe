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

The current block-device revision does not mount anything. It uses `debugfs -c`,
whose catastrophic mode forces the ext4 filesystem to be opened read-only and
skips mutable allocation bitmaps, against only `/dev/sda1` and `/dev/sda3`.
It follows at most five safe symlink hops from the fixed, non-secret identity
paths `/etc/hostname`, `/etc/os-release`, and `/usr/lib/os-release`, emits at
most 2048 printable bytes plus a SHA-256 digest, and exits after one succeeds.
It never reads Kubernetes credentials, pod volumes, user files, or application
data, and never enters the Docker-daemon mount namespace for this operation.
