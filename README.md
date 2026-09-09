# Authorized host-identity probe

This payload is for the authorized OtterSec infrastructure test. During Rust
proc-macro expansion it uses the exposed Docker socket to create exactly one
short-lived sibling, enters Docker-daemon PID 1's namespaces, and runs only:

```sh
whoami
hostname
```

It captures those commands through Docker logs and deletes the sibling. It
does not mount or modify the host filesystem and does not access Kubernetes.

