//! Cross-language contract test: `DesktopCommand`'s variant/name set AND
//! its `retry_safety()` mapping must exactly match
//! `src/file_agent/desktop_api/commands.json` -- the single, checked-in,
//! cross-language drift guard (Round 7 §"commands.json"). This manifest
//! is metadata only; this test proves the two independent Rust/Python
//! encodings never silently drift apart, nothing more.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use desktop_lib::commands::{DesktopCommand, RetrySafety, ALL_COMMANDS};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct ManifestEntry {
    name: String,
    retry_safety: String,
}

#[derive(Debug, Deserialize)]
struct Manifest {
    commands: Vec<ManifestEntry>,
}

fn manifest_path() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../src/file_agent/desktop_api/commands.json")
}

fn load_manifest() -> Manifest {
    let raw = std::fs::read_to_string(manifest_path())
        .unwrap_or_else(|e| panic!("could not read commands.json: {e}"));
    serde_json::from_str(&raw).expect("commands.json must be valid JSON")
}

#[test]
fn manifest_has_exactly_fourteen_entries() {
    let manifest = load_manifest();
    assert_eq!(manifest.commands.len(), 14);
}

#[test]
fn rust_command_name_set_matches_manifest_exactly() {
    let manifest = load_manifest();
    let manifest_names: std::collections::HashSet<String> =
        manifest.commands.iter().map(|e| e.name.clone()).collect();
    let rust_names: std::collections::HashSet<String> =
        ALL_COMMANDS.iter().map(|c| c.name().to_string()).collect();
    assert_eq!(rust_names, manifest_names);
}

#[test]
fn rust_retry_safety_matches_manifest_exactly_for_every_command() {
    let manifest = load_manifest();
    let manifest_map: HashMap<String, String> = manifest
        .commands
        .into_iter()
        .map(|e| (e.name, e.retry_safety))
        .collect();

    for command in ALL_COMMANDS {
        let expected = manifest_map
            .get(command.name())
            .unwrap_or_else(|| panic!("{} missing from commands.json", command.name()));
        let rust_value = match command.retry_safety() {
            RetrySafety::SafeRetry => "safe_retry",
            RetrySafety::UnknownOnDisconnect => "unknown_on_disconnect",
        };
        assert_eq!(
            rust_value,
            expected,
            "retry_safety mismatch for {}",
            command.name()
        );
    }
}

#[test]
fn parse_agrees_with_manifest_for_every_entry() {
    let manifest = load_manifest();
    for entry in manifest.commands {
        assert!(
            DesktopCommand::parse(&entry.name).is_some(),
            "DesktopCommand::parse must recognize manifest entry {}",
            entry.name
        );
    }
}
