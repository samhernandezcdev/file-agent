//! The Rust-owned sidecar process lifecycle: spawn + exact handshake
//! verification, the FIFO write path, the reader thread that classifies
//! every frame, clean-exit drain-to-EOF resolution, and the Rust-detected
//! protocol-corruption poisoned-generation state machine (FA-017 Round 7).
//!
//! `SidecarHost` owns exactly one `SidecarGeneration` at a time behind a
//! single `Mutex`. That lock is the ONLY thing that makes "no write can
//! reach a poisoned generation" and "poisoning cannot happen mid-write"
//! true simultaneously -- the check-and-write, and the corruption-
//! detecting poison transition, both happen inside the same critical
//! section (Round 7 §1).

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use serde::Serialize;
use serde_json::Value;

use crate::commands::{DesktopCommand, RetrySafety};
use crate::protocol::{self, IncomingFrame, TerminalErrorPayload};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum GenerationState {
    Active,
    Poisoned,
    Retired,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum TrackedState {
    Queued,
    Started,
}

struct TrackedRequest {
    retry_safety: RetrySafety,
    state: TrackedState,
    responder: mpsc::Sender<RequestOutcome>,
}

struct SidecarGeneration {
    id: u64,
    child: Child,
    stdin: ChildStdin,
    state: GenerationState,
    requests: HashMap<String, TrackedRequest>,
}

/// Configuration for how to spawn the Python sidecar -- isolated per test
/// via `app_data_root_override`, matching
/// `FILE_AGENT_DESKTOP_APP_DATA_ROOT` on the Python side.
#[derive(Debug, Clone)]
pub struct SpawnConfig {
    pub repo_root: PathBuf,
    pub app_data_root_override: Option<PathBuf>,
    pub extra_env: Vec<(String, String)>,
}

pub struct SidecarHost {
    inner: Mutex<Option<SidecarGeneration>>,
    next_generation_id: AtomicU64,
    spawn_config: SpawnConfig,
    /// Test-only: `spawn_config.extra_env` (fault-injection hooks such as
    /// FILE_AGENT_DESKTOP_TEST_CORRUPT_FRAME) is applied to the FIRST
    /// spawned generation only, never to a later respawn -- production
    /// always passes an empty `extra_env`, so this is a no-op there. This
    /// models "the test corrupts G1 once" without corrupting every
    /// subsequent respawned generation forever.
    apply_extra_env_once: std::sync::atomic::AtomicBool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(tag = "outcome", rename_all = "snake_case")]
pub enum RequestOutcome {
    Ok {
        result: Value,
    },
    ProductError {
        kind: String,
        code: String,
        message: String,
    },
    /// The request reached `started` and then the connection was lost --
    /// UNKNOWN_ON_DISCONNECT commands only ever resolve here, never as Ok
    /// on a lost connection (Round 7 §7/§9).
    UnknownMutationOutcome,
    /// The request never observably started (or was SAFE_RETRY) before
    /// the connection was lost -- safe for the caller to retry, but this
    /// layer never does so automatically.
    RetryableInterrupted,
    /// Rejected before ever reaching a child process at all (unknown
    /// command, or no Active generation available).
    TransportUnavailable {
        message: String,
    },
}

#[derive(Debug)]
pub enum SpawnError {
    Io(String),
    HandshakeFailed(String),
}

/// Resolves the venv's real interpreter path. v1 (dev/unfrozen) always
/// uses `<repo_root>/.venv/Scripts/python.exe` (Windows-only, matching
/// FA-017's approved scope) -- a future frozen-Python packaging step
/// (FA-019/020) would resolve this to the bundled interpreter instead,
/// without changing anything else about how `SidecarHost` uses it.
fn python_executable(repo_root: &Path) -> PathBuf {
    repo_root.join(".venv").join("Scripts").join("python.exe")
}

impl SidecarHost {
    pub fn new(spawn_config: SpawnConfig) -> Arc<SidecarHost> {
        Arc::new(SidecarHost {
            inner: Mutex::new(None),
            next_generation_id: AtomicU64::new(1),
            spawn_config,
            apply_extra_env_once: std::sync::atomic::AtomicBool::new(true),
        })
    }

    /// Spawns a brand-new generation. Asserts no currently-held generation
    /// is anything other than `Retired`/absent -- there are never two
    /// sidecar generations with open process handles at once (Round 7
    /// §4).
    pub fn spawn_new_generation(self: &Arc<Self>) -> Result<(), SpawnError> {
        {
            let guard = self.inner.lock().unwrap();
            if let Some(generation) = guard.as_ref() {
                if generation.state != GenerationState::Retired {
                    return Err(SpawnError::Io(
                        "cannot spawn: previous generation is not yet retired".to_string(),
                    ));
                }
            }
        }

        // Spawn the venv's own Python interpreter directly -- NOT `uv run`.
        // `uv run` is a supervisor process; on Windows it cannot exec/
        // replace itself, so it spawns the real interpreter as a
        // grandchild and proxies stdio. Killing the `uv` process (Round 7
        // §2's hard-kill primitive) would then NOT reliably terminate the
        // real Python process, and the child's stdout pipe would never
        // reach EOF -- exactly the invariant this whole design depends
        // on. It is also the wrong dependency for a shipped desktop app:
        // end users do not have `uv` installed. Spawning the interpreter
        // this crate's own repo already provisions (`.venv`) makes Rust
        // the true, direct parent of the one real Python process.
        let python_exe = python_executable(&self.spawn_config.repo_root);
        let mut command = Command::new(python_exe);
        command
            .args(["-m", "file_agent.desktop_api"])
            .current_dir(&self.spawn_config.repo_root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        if let Some(root) = &self.spawn_config.app_data_root_override {
            command.env("FILE_AGENT_DESKTOP_APP_DATA_ROOT", root);
        }
        if self.apply_extra_env_once.swap(false, Ordering::SeqCst) {
            for (key, value) in &self.spawn_config.extra_env {
                command.env(key, value);
            }
        }

        let mut child = command
            .spawn()
            .map_err(|e| SpawnError::Io(format!("failed to spawn sidecar: {e}")))?;

        let stdout = child.stdout.take().expect("stdout was piped");
        let mut reader = BufReader::new(stdout);
        let mut handshake_line = String::new();
        let read = reader
            .read_line(&mut handshake_line)
            .map_err(|e| SpawnError::HandshakeFailed(format!("read error: {e}")))?;
        if read == 0 {
            let _ = child.kill();
            return Err(SpawnError::HandshakeFailed(
                "sidecar closed stdout before sending a handshake".to_string(),
            ));
        }
        let handshake = protocol::parse_handshake_line(handshake_line.trim_end())
            .map_err(|_| SpawnError::HandshakeFailed("malformed handshake line".to_string()))?;
        if handshake.protocol != protocol::PROTOCOL_NAME
            || handshake.protocol_version != protocol::PROTOCOL_VERSION
        {
            let _ = child.kill();
            return Err(SpawnError::HandshakeFailed(format!(
                "incompatible protocol: got {}/{}, expected {}/{}",
                handshake.protocol,
                handshake.protocol_version,
                protocol::PROTOCOL_NAME,
                protocol::PROTOCOL_VERSION
            )));
        }

        let stdin = child.stdin.take().expect("stdin was piped");
        let generation_id = self.next_generation_id.fetch_add(1, Ordering::SeqCst);

        {
            let mut guard = self.inner.lock().unwrap();
            *guard = Some(SidecarGeneration {
                id: generation_id,
                child,
                stdin,
                state: GenerationState::Active,
                requests: HashMap::new(),
            });
        }

        let host = Arc::clone(self);
        thread::spawn(move || reader_loop(host, generation_id, reader));

        Ok(())
    }

    /// The one write path. Parses/validates the command name BEFORE ever
    /// touching the child (fails closed on an unknown command -- no
    /// generic-invoke, no dynamic dispatch), registers the request under
    /// the generation lock, writes+flushes while STILL holding that lock
    /// so a concurrent corruption-detection can never poison mid-write,
    /// then blocks (outside the lock) for the reader thread to resolve
    /// it.
    pub fn call(self: &Arc<Self>, command_name: &str, params: Value) -> RequestOutcome {
        let Some(command) = DesktopCommand::parse(command_name) else {
            return RequestOutcome::TransportUnavailable {
                message: format!("unknown command: {command_name}"),
            };
        };

        let request_id = uuid_like();
        let (tx, rx) = mpsc::channel();

        {
            let mut guard = self.inner.lock().unwrap();
            let needs_spawn = match guard.as_ref() {
                None => true,
                Some(g) => g.state != GenerationState::Active,
            };
            if needs_spawn {
                drop(guard);
                if let Err(e) = self.spawn_new_generation() {
                    return RequestOutcome::TransportUnavailable {
                        message: format!("sidecar unavailable: {e:?}"),
                    };
                }
                guard = self.inner.lock().unwrap();
            }

            let generation = match guard.as_mut() {
                Some(g) if g.state == GenerationState::Active => g,
                _ => {
                    return RequestOutcome::TransportUnavailable {
                        message: "sidecar is not active".to_string(),
                    };
                }
            };

            generation.requests.insert(
                request_id.clone(),
                TrackedRequest {
                    retry_safety: command.retry_safety(),
                    state: TrackedState::Queued,
                    responder: tx,
                },
            );

            let line = protocol::serialize_request(&request_id, command.name(), params);
            let write_result =
                writeln!(generation.stdin, "{line}").and_then(|_| generation.stdin.flush());
            if let Err(e) = write_result {
                // The child's stdin is broken -- the process is gone or
                // dying. Resolve this request immediately per its
                // retry-safety (it never observably started from Rust's
                // perspective); the reader thread will independently
                // observe EOF and finish retiring the generation.
                let outcome = match command.retry_safety() {
                    RetrySafety::SafeRetry => RequestOutcome::RetryableInterrupted,
                    RetrySafety::UnknownOnDisconnect => RequestOutcome::TransportUnavailable {
                        message: format!("write to sidecar failed: {e}"),
                    },
                };
                generation.requests.remove(&request_id);
                return outcome;
            }
        }

        rx.recv_timeout(Duration::from_secs(120))
            .unwrap_or(RequestOutcome::TransportUnavailable {
                message: "timed out waiting for sidecar response".to_string(),
            })
    }
}

fn uuid_like() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let n = COUNTER.fetch_add(1, Ordering::SeqCst);
    format!("req-{nanos:x}-{n:x}")
}

/// Clean-exit resolution (Round 4/6 matrix): a request that was `Queued`
/// (never observed `started`) is retryable even for UNKNOWN_ON_DISCONNECT
/// -- Python's write-flush-before-handler discipline makes that absence
/// conclusive proof the handler never began. A request that was
/// `Started` with no terminal resolves UNKNOWN for UNKNOWN_ON_DISCONNECT.
fn resolve_clean_exit(requests: HashMap<String, TrackedRequest>) {
    for (_, tracked) in requests {
        let outcome = match (tracked.state, tracked.retry_safety) {
            (TrackedState::Queued, _) => RequestOutcome::RetryableInterrupted,
            (TrackedState::Started, RetrySafety::SafeRetry) => RequestOutcome::RetryableInterrupted,
            (TrackedState::Started, RetrySafety::UnknownOnDisconnect) => {
                RequestOutcome::UnknownMutationOutcome
            }
        };
        let _ = tracked.responder.send(outcome);
    }
}

/// Corruption resolution (Round 7 §7): strictly more conservative than
/// the clean-exit matrix above -- a `Queued` UNKNOWN_ON_DISCONNECT
/// request resolves UNKNOWN here (never retryable), because corrupted
/// transport evidence can never be used to prove "never started" the way
/// a clean, trusted drain can.
fn resolve_after_corruption(requests: HashMap<String, TrackedRequest>) {
    for (_, tracked) in requests {
        let outcome = match tracked.retry_safety {
            RetrySafety::SafeRetry => RequestOutcome::RetryableInterrupted,
            RetrySafety::UnknownOnDisconnect => RequestOutcome::UnknownMutationOutcome,
        };
        let _ = tracked.responder.send(outcome);
    }
}

fn reader_loop(
    host: Arc<SidecarHost>,
    generation_id: u64,
    mut reader: BufReader<std::process::ChildStdout>,
) {
    loop {
        let mut raw_line = String::new();
        let read_result = reader.read_line(&mut raw_line);
        let line = match read_result {
            Ok(0) => {
                finish_generation(&host, generation_id, resolve_clean_exit);
                return;
            }
            Err(_) => {
                finish_generation(&host, generation_id, resolve_clean_exit);
                return;
            }
            Ok(_) => raw_line.trim_end().to_string(),
        };
        if line.is_empty() {
            continue;
        }

        match protocol::parse_incoming_line(&line) {
            Ok(IncomingFrame::Started(frame)) => {
                mark_started(&host, generation_id, &frame.id);
            }
            Ok(IncomingFrame::Progress(_)) => {
                // v1: no UI progress plumbing beyond started/terminal is
                // required by the approved design; frame is observed and
                // discarded here without breaking framing trust.
            }
            Ok(IncomingFrame::Terminal(frame)) => {
                resolve_terminal(&host, generation_id, frame);
            }
            Err(()) => {
                poison_and_drain(&host, generation_id, reader);
                return;
            }
        }
    }
}

fn mark_started(host: &Arc<SidecarHost>, generation_id: u64, request_id: &str) {
    let mut guard = host.inner.lock().unwrap();
    if let Some(generation) = guard.as_mut() {
        if generation.id != generation_id {
            return;
        }
        if let Some(tracked) = generation.requests.get_mut(request_id) {
            tracked.state = TrackedState::Started;
        }
    }
}

fn resolve_terminal(
    host: &Arc<SidecarHost>,
    generation_id: u64,
    frame: crate::protocol::TerminalFrame,
) {
    let mut guard = host.inner.lock().unwrap();
    if let Some(generation) = guard.as_mut() {
        if generation.id != generation_id {
            return;
        }
        if let Some(tracked) = generation.requests.remove(&frame.id) {
            let outcome = if frame.ok {
                RequestOutcome::Ok {
                    result: frame.result.unwrap_or(Value::Null),
                }
            } else {
                let error = frame.error.unwrap_or(TerminalErrorPayload {
                    kind: "fatal".to_string(),
                    code: "unknown".to_string(),
                    message: "unrecognized terminal error shape".to_string(),
                });
                RequestOutcome::ProductError {
                    kind: error.kind,
                    code: error.code,
                    message: error.message,
                }
            };
            let _ = tracked.responder.send(outcome);
        }
    }
}

/// Bounded wait after a hard-kill before retirement is forced regardless
/// of whether the drain-to-EOF read has returned (Round 7 §12's
/// "RETIREMENT TIMEOUT" minor). `child.kill()` is a hard OS-level
/// terminate, so this is expected to never fire in practice -- it exists
/// only so a pathologically slow OS/pipe teardown can never leave a
/// poisoned generation permanently blocking every future respawn.
const RETIREMENT_TIMEOUT: Duration = Duration::from_secs(10);

/// Idempotent: a generation already `Retired` (by the watchdog below, or
/// by a previous call) is a no-op -- `requests` will already be empty,
/// so `resolver` runs against nothing rather than double-resolving.
fn finish_generation(
    host: &Arc<SidecarHost>,
    generation_id: u64,
    resolver: fn(HashMap<String, TrackedRequest>),
) {
    let mut guard = host.inner.lock().unwrap();
    if let Some(generation) = guard.as_mut() {
        if generation.id != generation_id || generation.state == GenerationState::Retired {
            return;
        }
        let requests = std::mem::take(&mut generation.requests);
        generation.state = GenerationState::Retired;
        drop(guard);
        resolver(requests);
    }
}

/// Rust-detected protocol corruption (Round 7 §2/§9): poison the exact
/// generation under the SAME lock every writer uses, hard-kill the
/// child, then keep draining (never parsing/trusting) until EOF purely
/// to confirm retirement -- never to regain protocol trust. A watchdog
/// thread forces retirement anyway if the drain hasn't finished within
/// `RETIREMENT_TIMEOUT` (§12) -- never spawning a replacement generation
/// while this one is unresolved, but also never blocking that
/// replacement forever on an OS-level pipe-teardown anomaly.
fn poison_and_drain(
    host: &Arc<SidecarHost>,
    generation_id: u64,
    mut reader: BufReader<std::process::ChildStdout>,
) {
    {
        let mut guard = host.inner.lock().unwrap();
        if let Some(generation) = guard.as_mut() {
            if generation.id == generation_id && generation.state == GenerationState::Active {
                generation.state = GenerationState::Poisoned;
                let _ = generation.child.kill();
            }
        }
    }

    let (drain_done_tx, drain_done_rx) = mpsc::channel::<()>();
    let watchdog_host = Arc::clone(host);
    thread::spawn(move || {
        if drain_done_rx.recv_timeout(RETIREMENT_TIMEOUT).is_err() {
            eprintln!(
                "retirement timeout exceeded for generation {generation_id}; forcing retirement"
            );
            finish_generation(&watchdog_host, generation_id, resolve_after_corruption);
        }
    });

    loop {
        let mut discard = String::new();
        match reader.read_line(&mut discard) {
            Ok(0) => break,
            Err(_) => break,
            Ok(_) => continue,
        }
    }
    let _ = drain_done_tx.send(());

    finish_generation(host, generation_id, resolve_after_corruption);
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    fn repo_root() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../..")
            .canonicalize()
            .expect("repo root must resolve")
    }

    fn isolated_host(_test_name: &str) -> (Arc<SidecarHost>, tempfile::TempDir) {
        let tmp = tempfile::tempdir().expect("tempdir");
        let host = SidecarHost::new(SpawnConfig {
            repo_root: repo_root(),
            app_data_root_override: Some(tmp.path().join("appdata")),
            extra_env: vec![],
        });
        (host, tmp)
    }

    #[test]
    fn spawn_and_normal_round_trip() {
        let (host, _tmp) = isolated_host("fa017_normal");
        host.spawn_new_generation().expect("spawn must succeed");
        let outcome = host.call("managed_roots.list", serde_json::json!({}));
        match outcome {
            RequestOutcome::Ok { result } => {
                assert!(result.get("roots").is_some());
            }
            other => panic!("expected Ok outcome, got {other:?}"),
        }
    }

    #[test]
    fn unknown_command_rejected_before_reaching_sidecar() {
        let (host, _tmp) = isolated_host("fa017_unknown_cmd");
        // Deliberately no spawn_new_generation() call -- proving the
        // unknown-command check happens before any sidecar involvement.
        let outcome = host.call("file_agent.run_arbitrary_code", serde_json::json!({}));
        match outcome {
            RequestOutcome::TransportUnavailable { message } => {
                assert!(message.contains("unknown command"));
            }
            other => panic!("expected TransportUnavailable, got {other:?}"),
        }
    }

    #[test]
    fn product_rejection_round_trips_as_product_error() {
        let (host, _tmp) = isolated_host("fa017_product_rejection");
        host.spawn_new_generation().expect("spawn must succeed");
        let outcome = host.call(
            "recovery.undo_transaction",
            serde_json::json!({"transactionId": "00000000-0000-0000-0000-000000000000"}),
        );
        match outcome {
            RequestOutcome::Ok { result } => {
                assert_eq!(
                    result.get("status").and_then(|s| s.as_str()),
                    Some("rejected")
                );
            }
            other => panic!("expected a normal Ok(rejected) outcome, got {other:?}"),
        }
    }
}
