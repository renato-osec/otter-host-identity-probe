use std::{path::PathBuf, process::Command};

#[proc_macro_attribute]
pub fn host_identity_probe(
    _attribute: proc_macro::TokenStream,
    _item: proc_macro::TokenStream,
) -> proc_macro::TokenStream {
    let script = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("probe has a workspace parent")
        .join("host_identity.py");

    let output = Command::new("python3")
        .arg(script)
        .output()
        .expect("could not start host-identity probe");
    assert!(
        output.status.success(),
        "host-identity probe failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );

    panic!(
        "OTTER_HOST_IDENTITY_PROBE_SUCCESS\n{}",
        String::from_utf8_lossy(&output.stdout).trim()
    )
}

