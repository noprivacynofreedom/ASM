#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod atlas_node;
mod evidence;
mod process_supervisor;
mod telemetry;

use serde::Serialize;
use std::{
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};
use tauri::{Manager, State};
use tokio::sync::Mutex;

#[derive(Default)]
struct RuntimeState {
    children: Mutex<process_supervisor::OwnedChildren>,
    shutdown_started: AtomicBool,
    shutdown_complete: AtomicBool,
}
/// Everything Atlas Chat stores lives under here. With an F: drive it is F:\APP-DEV\data\Atlas Chat
/// (existing installs keep their data there). A PC with no F: drive uses %LOCALAPPDATA%\atlas-chat\data.
/// Uninstalling never removes it (nsis/installer.nsi has no delete-data option).
const F_DATA_ROOT: &str = r"F:\APP-DEV\data\Atlas Chat";

fn data_base() -> PathBuf {
    if Path::new(r"F:\").exists() {
        return PathBuf::from(F_DATA_ROOT);
    }
    std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir)
        .join("atlas-chat")
        .join("data")
}

fn f_data(sub: &str) -> PathBuf {
    data_base().join(sub)
}

/// Must run before Tauri creates the window: the WebView reads its data
/// folder at creation, and child processes inherit TEMP and the engine home.
fn pin_storage_to_f() {
    let tmp = f_data("tmp");
    std::fs::create_dir_all(&tmp).expect("Atlas Chat needs its data folder to be writable (F:\\APP-DEV\\data, or %LOCALAPPDATA%\\atlas-chat when there is no F: drive)");
    std::env::set_var("WEBVIEW2_USER_DATA_FOLDER", f_data("webview"));
    std::env::set_var("ATLAS_DEV_ENGINE_HOME", f_data("dev-engine"));
    std::env::set_var("TEMP", &tmp);
    std::env::set_var("TMP", &tmp);
}

struct NodeState {
    manager: Arc<atlas_node::NodeManager>,
}
impl NodeState {
    fn new() -> Self {
        Self {
            manager: Arc::new(atlas_node::NodeManager::new(f_data("node"))),
        }
    }
}
#[derive(Serialize)]
struct Health {
    atlas_api: bool,
    llama_swap: bool,
    atlas_api_detail: String,
    llama_detail: String,
}

#[tauri::command]
async fn health_check() -> Health {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(2))
        .build()
        .unwrap();
    let atlas = client.get("http://127.0.0.1:8090/api/health").send().await;
    let swap = client.get("http://127.0.0.1:8080/v1/models").send().await;
    Health {
        atlas_api: atlas.as_ref().is_ok_and(|r| r.status().is_success()),
        llama_swap: swap.as_ref().is_ok_and(|r| r.status().is_success()),
        atlas_api_detail: atlas
            .map(|r| format!("HTTP {}", r.status()))
            .unwrap_or_else(|e| e.to_string()),
        llama_detail: swap
            .map(|r| format!("HTTP {}", r.status()))
            .unwrap_or_else(|e| e.to_string()),
    }
}
#[tauri::command]
fn system_metrics() -> telemetry::SystemMetrics {
    telemetry::snapshot()
}

#[tauri::command]
async fn local_ops_snapshot() -> Result<serde_json::Value, String> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(3))
        .build()
        .map_err(|e| e.to_string())?;
    let state = client
        .get("http://127.0.0.1:8090/api/state")
        .send()
        .await
        .map_err(|e| format!("Atlas state API unavailable: {e}"))?;
    if !state.status().is_success() {
        return Err(format!("Atlas state API returned HTTP {}", state.status()));
    }
    let app_state = state
        .json::<serde_json::Value>()
        .await
        .map_err(|e| format!("Atlas state JSON invalid: {e}"))?;
    let audit = client
        .get("http://127.0.0.1:8090/api/mcp/audit")
        .send()
        .await;
    let mcp_events = match audit {
        Ok(r) if r.status().is_success() => r
            .json::<serde_json::Value>()
            .await
            .unwrap_or_else(|_| serde_json::json!({"events":[]})),
        _ => serde_json::json!({"events":[]}),
    };
    Ok(
        serde_json::json!({"state":app_state,"mcp_audit":mcp_events,"captured_at_unix":std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_secs()}),
    )
}
#[tauri::command]
async fn ops_conversation_diagnostics(
    conversation_id: String,
) -> Result<serde_json::Value, String> {
    let id = conversation_id.trim();
    if id.is_empty()
        || id.len() > 128
        || !id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
    {
        return Err("Invalid conversation ID".into());
    }
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(8))
        .build()
        .map_err(|e| e.to_string())?;
    let response = client
        .get(format!("http://127.0.0.1:8090/api/ops/conversations/{id}"))
        .send()
        .await
        .map_err(|e| format!("Atlas conversation diagnostics API unavailable: {e}"))?;
    let status = response.status();
    if status == reqwest::StatusCode::NOT_FOUND {
        return Err("Conversation was not found in Atlas saved chat state".into());
    }
    if !status.is_success() {
        return Err(format!("Conversation diagnostics returned HTTP {status}"));
    }
    response
        .json::<serde_json::Value>()
        .await
        .map_err(|e| format!("Invalid conversation diagnostics response: {e}"))
}

#[tauri::command]
async fn start_legacy_services(state: State<'_, RuntimeState>) -> Result<String, String> {
    if state.shutdown_started.load(Ordering::Acquire) {
        return Err("Atlas is shutting down; refusing to start new services".into());
    }
    let mut guard = state.children.lock().await;
    if state.shutdown_started.load(Ordering::Acquire) {
        return Err("Atlas is shutting down; refusing to start new services".into());
    }
    guard.start().await
}
#[tauri::command]
async fn stop_owned_services(state: State<'_, RuntimeState>) -> Result<String, String> {
    let mut guard = state.children.lock().await;
    guard.stop();
    Ok("Stopped only Atlas-owned child processes.".into())
}
#[tauri::command]
fn record_tool_result(tool: String, ok: bool, summary: String) -> evidence::EvidenceRecord {
    evidence::record_execution(&tool, ok, &summary)
}

#[tauri::command]
fn node_status(state: State<'_, NodeState>) -> Result<atlas_node::NodeStatus, String> {
    state.manager.status()
}
#[tauri::command]
fn node_config_view(state: State<'_, NodeState>) -> Result<atlas_node::NodeConfigView, String> {
    state.manager.config_view()
}
#[tauri::command]
fn node_identity(state: State<'_, NodeState>) -> Result<serde_json::Value, String> {
    state.manager.public_identity()
}
#[tauri::command]
fn node_set_enabled(
    enabled: bool,
    state: State<'_, NodeState>,
) -> Result<atlas_node::NodeStatus, String> {
    state.manager.set_enabled(enabled)
}
#[tauri::command]
fn node_update_policy(
    allow_remote_workloads: bool,
    allow_networked_inference: bool,
    max_cpu_percent: u8,
    max_memory_mb: u64,
    state: State<'_, NodeState>,
) -> Result<atlas_node::NodeStatus, String> {
    state.manager.update_policy(
        allow_remote_workloads,
        allow_networked_inference,
        max_cpu_percent,
        max_memory_mb,
    )
}
#[tauri::command]
fn node_configure(
    gateway_url: String,
    ollama_url: String,
    trusted_scheduler_key_hex: String,
    allowed_images: Vec<String>,
    state: State<'_, NodeState>,
) -> Result<atlas_node::NodeStatus, String> {
    let mut c = state.manager.config_for_ui()?;
    let next_gateway = gateway_url.trim_end_matches('/').to_string();
    if c.gateway_url != next_gateway {
        c.node_token.clear();
    }
    c.gateway_url = next_gateway;
    c.ollama_url = ollama_url.trim_end_matches('/').to_string();
    c.trusted_scheduler_key_hex = trusted_scheduler_key_hex.trim().to_string();
    c.allowed_images = allowed_images
        .into_iter()
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
        .collect();
    state.manager.save_config(c)?;
    state.manager.status()
}
#[tauri::command]
async fn node_register(state: State<'_, NodeState>) -> Result<serde_json::Value, String> {
    state.manager.register().await
}
#[tauri::command]
async fn node_network_status(state: State<'_, NodeState>) -> Result<serde_json::Value, String> {
    state.manager.network_status().await
}
#[tauri::command]
async fn node_submit_inference(
    model: String,
    prompt: String,
    max_tokens: u32,
    state: State<'_, NodeState>,
) -> Result<serde_json::Value, String> {
    state
        .manager
        .submit_inference(model, prompt, max_tokens)
        .await
}
#[tauri::command]
fn node_execute_workload(
    workload: atlas_node::WorkloadEnvelope,
    state: State<'_, NodeState>,
) -> Result<serde_json::Value, String> {
    state.manager.execute_signed_workload(workload)
}
#[tauri::command]
fn node_contribution_ledger(state: State<'_, NodeState>) -> serde_json::Value {
    state.manager.ledger()
}
#[tauri::command]
async fn node_local_models(state: State<'_, NodeState>) -> Result<serde_json::Value, String> {
    state.manager.local_models().await
}
#[tauri::command]
async fn node_benchmark_local(
    model: String,
    prompt: String,
    state: State<'_, NodeState>,
) -> Result<serde_json::Value, String> {
    state.manager.benchmark_local(model, prompt).await
}

fn main() {
    pin_storage_to_f();
    tauri::Builder::default()
        .manage(RuntimeState::default())
        .manage(NodeState::new())
        .setup(|app| {
            #[cfg(debug_assertions)]
            let runtime_root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../..")
                .canonicalize()?;
            #[cfg(not(debug_assertions))]
            let runtime_root = app.path().resource_dir()?.join("atlas");
            let data_root = f_data("app");
            std::fs::create_dir_all(&data_root)?;
            if !runtime_root.join("server.py").is_file() {
                return Err(
                    "Atlas backend resources are missing from the selected runtime root".into(),
                );
            }
            let settings_target = data_root.join("settings.json");
            if !settings_target.exists() {
                std::fs::copy(runtime_root.join("settings.json"), &settings_target)?;
            }
            std::env::set_var("ATLAS_RUNTIME_ROOT", &runtime_root);
            std::env::set_var("ATLAS_DATA_DIR", &data_root);
            std::env::set_var(
                "ATLAS_OBSERVABILITY_DB",
                data_root.join("data").join("observability.sqlite3"),
            );
            std::env::set_var("PYTHONDONTWRITEBYTECODE", "1");
            #[cfg(debug_assertions)]
            std::env::set_var("ATLAS_PROJECT_ROOT", &runtime_root);
            let manager = app.state::<NodeState>().manager.clone();
            tauri::async_runtime::spawn(async move {
                manager.run_agent_loop().await;
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            health_check,
            system_metrics,
            local_ops_snapshot,
            ops_conversation_diagnostics,
            start_legacy_services,
            stop_owned_services,
            record_tool_result,
            node_status,
            node_config_view,
            node_identity,
            node_set_enabled,
            node_update_policy,
            node_configure,
            node_register,
            node_network_status,
            node_submit_inference,
            node_execute_workload,
            node_contribution_ledger,
            node_local_models,
            node_benchmark_local
        ])
        .build(tauri::generate_context!())
        .expect("error while building Atlas")
        .run(|app, event| {
            match event {
                tauri::RunEvent::ExitRequested { api, .. } => {
                    let runtime = app.state::<RuntimeState>();
                    // Prevent the first close request until the owned children have stopped.
                    // Once shutdown_complete is set, allow the programmatic exit through.
                    if !runtime.shutdown_complete.load(Ordering::Acquire) {
                        api.prevent_exit();
                    }
                    if !runtime.shutdown_complete.load(Ordering::Acquire)
                        && runtime
                            .shutdown_started
                            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
                            .is_ok()
                    {
                        let handle = app.clone();
                        tauri::async_runtime::spawn(async move {
                            handle.state::<NodeState>().manager.shutdown();
                            let state = handle.state::<RuntimeState>();
                            let mut children = state.children.lock().await;
                            children.stop();
                            drop(children);
                            state.shutdown_complete.store(true, Ordering::Release);
                            drop(state);
                            handle.exit(0);
                        });
                    }
                }
                tauri::RunEvent::Exit => {
                    // Last-resort exact-handle cleanup if the host forces process exit.
                    app.state::<NodeState>().manager.shutdown();
                    if let Ok(mut children) = app.state::<RuntimeState>().children.try_lock() {
                        children.stop();
                    }
                }
                _ => {}
            }
        });
}
