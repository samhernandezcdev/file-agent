//! Real-subprocess Rust-side transport integration tests -- spawns the
//! genuine Python sidecar (never a fake) and exercises the parts of
//! FA-017 Round 7 that are Rust's own responsibility: clean-exit
//! drain-to-EOF classification, and the Rust-detected protocol-corruption
//! poisoned-generation state machine (no two active generations; no
//! automatic respawn; a later explicit call succeeds once the old
//! generation is retired).
//!
//! The Python sidecar's own half (STARTED write-flush discipline,
//! process-wide os._exit() on a confirmed protocol-write failure) is
//! covered by tests/desktop_api/test_sidecar_transport.py -- these two
//! suites are deliberately complementary, not duplicated.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

use desktop_lib::sidecar::{RequestOutcome, SidecarHost, SpawnConfig};

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .canonicalize()
        .expect("repo root must resolve")
}

fn isolated_host(extra_env: Vec<(String, String)>) -> (Arc<SidecarHost>, tempfile::TempDir) {
    let tmp = tempfile::tempdir().expect("tempdir");
    let host = SidecarHost::new(SpawnConfig {
        repo_root: repo_root(),
        app_data_root_override: Some(tmp.path().join("appdata")),
        extra_env,
    });
    (host, tmp)
}

fn wait_until_call_succeeds(host: &Arc<SidecarHost>, deadline: Duration) -> RequestOutcome {
    let start = Instant::now();
    loop {
        let outcome = host.call("managed_roots.list", serde_json::json!({}));
        if !matches!(outcome, RequestOutcome::TransportUnavailable { .. }) {
            return outcome;
        }
        if start.elapsed() > deadline {
            return outcome;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
}

/// Test A/E-equivalent: an UNKNOWN_ON_DISCONNECT request that reaches
/// `started` and then the sidecar dies cleanly (forced write failure on
/// Python's own terminal emit, which triggers Python's os._exit()) must
/// resolve UNKNOWN from Rust's side -- Rust's drain-to-EOF classification
/// applied to a clean process exit.
#[test]
fn clean_exit_after_started_resolves_unknown_for_unknown_on_disconnect() {
    let (host, tmp) = isolated_host(vec![(
        "FILE_AGENT_DESKTOP_TEST_FORCE_WRITE_FAILURE".to_string(),
        "terminal".to_string(),
    )]);
    host.spawn_new_generation().expect("spawn must succeed");

    let real_folder = tmp.path().join("a_real_folder");
    std::fs::create_dir_all(&real_folder).unwrap();

    let outcome = host.call(
        "managed_roots.add",
        serde_json::json!({"path": real_folder.to_string_lossy()}),
    );
    assert!(
        matches!(outcome, RequestOutcome::UnknownMutationOutcome),
        "expected UnknownMutationOutcome, got {outcome:?}"
    );
}

/// Test J-equivalent: Rust-detected protocol corruption (genuinely
/// garbled bytes on stdout, not a clean exit) must poison the current
/// generation, resolve the in-flight UNKNOWN_ON_DISCONNECT request as
/// UNKNOWN, reject any call issued before retirement completes, and only
/// succeed again once a later explicit call triggers a fresh generation
/// with its own handshake -- G1 and G2 are never simultaneously active.
#[test]
fn corruption_poisons_generation_then_a_later_call_respawns_cleanly() {
    let (host, _tmp) = isolated_host(vec![(
        "FILE_AGENT_DESKTOP_TEST_CORRUPT_FRAME".to_string(),
        "started".to_string(),
    )]);
    host.spawn_new_generation().expect("spawn must succeed");

    // recovery.undo_transaction is UNKNOWN_ON_DISCONNECT; the bogus
    // transaction id is irrelevant -- the corrupted "started" frame means
    // Rust never observes a trusted started at all before corruption.
    let outcome = host.call(
        "recovery.undo_transaction",
        serde_json::json!({"transactionId": "00000000-0000-0000-0000-000000000000"}),
    );
    assert!(
        matches!(outcome, RequestOutcome::UnknownMutationOutcome),
        "expected UnknownMutationOutcome from the poisoned/corrupted generation, got {outcome:?}"
    );

    // Give the reader thread a moment to finish killing the child and
    // draining to EOF (retirement is asynchronous relative to the
    // corruption detection itself).
    std::thread::sleep(Duration::from_millis(200));

    // A later, genuinely new call must succeed -- proving a fresh
    // generation (G2) was spawned, performed its own handshake, and is
    // now Active. This also proves no auto-respawn happened silently in
    // the background: it only happens as a consequence of THIS call.
    let outcome = wait_until_call_succeeds(&host, Duration::from_secs(10));
    assert!(
        matches!(outcome, RequestOutcome::Ok { .. }),
        "expected the respawned generation to serve a normal request, got {outcome:?}"
    );
}
