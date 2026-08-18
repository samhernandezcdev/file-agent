pub mod commands;
pub mod protocol;
pub mod sidecar;

use std::path::PathBuf;
use std::sync::Arc;

use serde_json::Value;
use tauri::Manager;

use sidecar::{RequestOutcome, SidecarHost, SpawnConfig};

/// The ONE narrow command the WebView may call to reach FileAgent's
/// Python core -- no shell, no fs, no http/network plugin authority.
/// `command_name` is validated against the closed 14-entry catalogue
/// before it ever reaches the sidecar (Round 7 §"CLOSED DESKTOP COMMAND
/// CATALOGUE"). UI intent is never authorization: this function forwards
/// intent only, the Python ApplicationService remains the sole
/// authorization boundary.
#[tauri::command]
fn desktop_call(
    host: tauri::State<Arc<SidecarHost>>,
    command: String,
    params: Value,
) -> RequestOutcome {
    host.call(&command, params)
}

fn repo_root_from_manifest_dir() -> PathBuf {
    // src-tauri/ -> apps/desktop/ -> apps/ -> repo root
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .canonicalize()
        .expect("repo root must resolve from CARGO_MANIFEST_DIR")
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default().plugin(tauri_plugin_dialog::init());
    // Off by default -- never present in a real release build. Only
    // `pnpm --filter desktop e2e` compiles with `--features e2e-testing`,
    // enabling the WebdriverIO test hook plugin so E2E specs can drive
    // the real, compiled app.
    #[cfg(feature = "e2e-testing")]
    let builder = builder
        .plugin(tauri_plugin_wdio::init())
        .plugin(tauri_plugin_wdio_webdriver::init());

    builder
        .invoke_handler(tauri::generate_handler![desktop_call])
        .setup(|app| {
            // The same env var Python's own bootstrap.py understands --
            // set by E2E fixtures to an isolated throwaway directory so
            // tests never touch the real %APPDATA%/FileAgent, and never
            // set in a normal user install.
            let app_data_root_override = std::env::var("FILE_AGENT_DESKTOP_APP_DATA_ROOT")
                .ok()
                .map(PathBuf::from);
            let host = SidecarHost::new(SpawnConfig {
                repo_root: repo_root_from_manifest_dir(),
                app_data_root_override,
                extra_env: vec![],
            });
            // Long-lived sidecar: spawned once at app startup, not lazily
            // per-command. A startup failure (incompatible/corrupted
            // install) is logged; desktop_call's own lazy-spawn fallback
            // still gives the user a retry path without restarting the
            // app, matching "no automatic respawn, only an explicit later
            // user action" for the poisoned-generation case.
            if let Err(e) = host.spawn_new_generation() {
                eprintln!("initial sidecar spawn failed: {e:?}");
            }
            app.manage(host);
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
