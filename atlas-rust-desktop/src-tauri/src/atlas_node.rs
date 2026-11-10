use ring::{
    digest,
    rand::SystemRandom,
    signature::{Ed25519KeyPair, KeyPair, UnparsedPublicKey, ED25519},
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    fs,
    path::PathBuf,
    process::{Command, Output, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex,
    },
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

// Every helper process launched by the GUI must stay invisible on Windows.
fn hidden_command(program: &str) -> Command {
    let mut command = Command::new(program);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    command
}
use sysinfo::{CpuRefreshKind, MemoryRefreshKind, RefreshKind, System};

#[derive(Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct NodeConfig {
    pub enabled: bool,
    pub allow_remote_workloads: bool,
    pub allow_networked_inference: bool,
    pub max_cpu_percent: u8,
    pub max_memory_mb: u64,
    pub gateway_url: String,
    pub ollama_url: String,
    pub trusted_scheduler_key_hex: String,
    #[serde(skip)]
    pub node_token: String,
    pub allowed_images: Vec<String>,
}
impl Default for NodeConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            allow_remote_workloads: false,
            allow_networked_inference: false,
            max_cpu_percent: 50,
            max_memory_mb: 4096,
            gateway_url: String::new(),
            ollama_url: "http://127.0.0.1:8080".into(),
            trusted_scheduler_key_hex: String::new(),
            node_token: String::new(),
            allowed_images: vec![],
        }
    }
}

#[derive(Clone, Default)]
struct HardwareSnapshot {
    gpus: Vec<GpuInfo>,
    sandbox_available: bool,
}

pub struct NodeManager {
    root: PathBuf,
    config: Mutex<NodeConfig>,
    active_child: Mutex<Option<std::process::Child>>,
    active_container_id: Mutex<Option<String>>,
    active_cidfile: Mutex<Option<PathBuf>>,
    hardware: Mutex<HardwareSnapshot>,
    shutting_down: AtomicBool,
}
#[derive(Clone, Serialize)]
pub struct GpuInfo {
    pub name: String,
    pub vendor: String,
    pub vram_total_mb: Option<u64>,
    pub vram_free_mb: Option<u64>,
    pub utilization_percent: Option<u64>,
    pub source: String,
}
#[derive(Serialize)]
pub struct NodeConfigView {
    pub enabled: bool,
    pub allow_remote_workloads: bool,
    pub allow_networked_inference: bool,
    pub max_cpu_percent: u8,
    pub max_memory_mb: u64,
    pub gateway_url: String,
    pub ollama_url: String,
    pub trusted_scheduler_key_hex: String,
    pub allowed_images: Vec<String>,
    pub registered: bool,
}
#[derive(Serialize)]
pub struct NodeStatus {
    pub node_id: String,
    pub enabled: bool,
    pub registered: bool,
    pub remote_workloads_allowed: bool,
    pub cpu_percent: f32,
    pub memory_total_mb: u64,
    pub memory_available_mb: u64,
    pub gpus: Vec<GpuInfo>,
    pub gateway_configured: bool,
    pub trusted_scheduler_configured: bool,
    pub sandbox_available: bool,
    pub local_ledger_entries: usize,
}
#[derive(Serialize, Deserialize)]
pub struct WorkloadEnvelope {
    pub workload_id: String,
    pub image: String,
    pub command: Vec<String>,
    pub max_memory_mb: u64,
    pub max_cpu_percent: u8,
    pub expires_at_unix: u64,
    pub nonce: String,
    pub signature_hex: String,
}

impl NodeManager {
    pub fn new(root: PathBuf) -> Self {
        let _ = fs::create_dir_all(&root);
        let mut cfg: NodeConfig = fs::read(root.join("node-config.json"))
            .ok()
            .and_then(|b| serde_json::from_slice(&b).ok())
            .unwrap_or_default();
        cfg.node_token = fs::read_to_string(root.join("node-token")).unwrap_or_default();
        Self {
            root,
            config: Mutex::new(cfg),
            active_child: Mutex::new(None),
            active_container_id: Mutex::new(None),
            active_cidfile: Mutex::new(None),
            hardware: Mutex::new(HardwareSnapshot::default()),
            shutting_down: AtomicBool::new(false),
        }
    }
    fn config_path(&self) -> PathBuf {
        self.root.join("node-config.json")
    }
    fn identity_path(&self) -> PathBuf {
        self.root.join("identity.pk8")
    }
    fn ledger_path(&self) -> PathBuf {
        self.root.join("contribution-ledger.jsonl")
    }
    fn token_path(&self) -> PathBuf {
        self.root.join("node-token")
    }
    fn claims_path(&self) -> PathBuf {
        self.root.join("workload-claims.jsonl")
    }
    pub fn config_for_ui(&self) -> Result<NodeConfig, String> {
        self.cfg()
    }
    fn http_client(timeout_secs: u64) -> Result<reqwest::Client, String> {
        reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(timeout_secs))
            .build()
            .map_err(|e| e.to_string())
    }
    fn cfg(&self) -> Result<NodeConfig, String> {
        self.config
            .lock()
            .map(|g| g.clone())
            .map_err(|_| "Node configuration lock poisoned".into())
    }
    pub fn save_config(&self, cfg: NodeConfig) -> Result<NodeConfig, String> {
        let current = self.cfg()?;
        if current.gateway_url != cfg.gateway_url && !current.node_token.is_empty() {
            self.cancel_active_workload();
        }
        if cfg.max_cpu_percent == 0 || cfg.max_cpu_percent > 100 {
            return Err("CPU limit must be between 1 and 100 percent".into());
        }
        if cfg.max_memory_mb < 256 {
            return Err("Memory limit must be at least 256 MB".into());
        }
        if !cfg.gateway_url.is_empty()
            && !(cfg.gateway_url.starts_with("https://")
                || cfg.gateway_url.starts_with("http://127.0.0.1:")
                || cfg.gateway_url.starts_with("http://localhost:"))
        {
            return Err("Gateway must use HTTPS, except localhost development".into());
        }
        fs::write(
            self.config_path(),
            serde_json::to_vec_pretty(&cfg).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
        if cfg.node_token.is_empty() {
            let _ = fs::remove_file(self.token_path());
        } else {
            fs::write(self.token_path(), cfg.node_token.as_bytes())
                .map_err(|e| format!("Cannot persist node credential: {e}"))?;
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = fs::set_permissions(self.config_path(), fs::Permissions::from_mode(0o600));
            let _ = fs::set_permissions(self.token_path(), fs::Permissions::from_mode(0o600));
        }
        *self
            .config
            .lock()
            .map_err(|_| "Node configuration lock poisoned")? = cfg.clone();
        Ok(cfg)
    }
    fn keypair(&self) -> Result<Ed25519KeyPair, String> {
        if self.identity_path().exists() {
            let bytes = fs::read(self.identity_path()).map_err(|e| e.to_string())?;
            return Ed25519KeyPair::from_pkcs8(&bytes).map_err(|_|"Stored Atlas Node identity is invalid; do not delete it unless you intend to create a new device identity".into());
        }
        let rng = SystemRandom::new();
        let doc = Ed25519KeyPair::generate_pkcs8(&rng)
            .map_err(|_| "Operating-system secure random generator unavailable".to_string())?;
        fs::write(self.identity_path(), doc.as_ref())
            .map_err(|e| format!("Cannot persist node identity: {e}"))?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = fs::set_permissions(self.identity_path(), fs::Permissions::from_mode(0o600));
        }
        Ed25519KeyPair::from_pkcs8(doc.as_ref()).map_err(|e| e.to_string())
    }
    fn node_id(&self) -> Result<String, String> {
        let kp = self.keypair()?;
        let h = digest::digest(&digest::SHA256, kp.public_key().as_ref());
        Ok(hex::encode(h.as_ref()))
    }
    pub fn status(&self) -> Result<NodeStatus, String> {
        let cfg = self.cfg()?;
        let mut sys = System::new_with_specifics(
            RefreshKind::nothing()
                .with_cpu(CpuRefreshKind::everything())
                .with_memory(MemoryRefreshKind::everything()),
        );
        sys.refresh_cpu_all();
        sys.refresh_memory();
        let total = sys.total_memory() / 1024 / 1024;
        let avail = sys.available_memory() / 1024 / 1024;
        let ledger = fs::read_to_string(self.ledger_path())
            .unwrap_or_default()
            .lines()
            .count();
        // Status is called by UI polling. It must never launch GPU/Docker probes.
        // Hardware discovery is performed by a background worker and cached.
        let hardware = self.hardware.lock().map(|v| v.clone()).unwrap_or_default();
        Ok(NodeStatus {
            node_id: self.node_id()?,
            enabled: cfg.enabled,
            registered: !cfg.node_token.is_empty(),
            remote_workloads_allowed: cfg.enabled && cfg.allow_remote_workloads,
            cpu_percent: sys.global_cpu_usage(),
            memory_total_mb: total,
            memory_available_mb: avail,
            gpus: hardware.gpus,
            gateway_configured: !cfg.gateway_url.is_empty(),
            trusted_scheduler_configured: cfg.trusted_scheduler_key_hex.len() == 64,
            sandbox_available: hardware.sandbox_available,
            local_ledger_entries: ledger,
        })
    }

    fn refresh_hardware(&self) {
        let gpus = detect_gpus();
        let sandbox_available = hidden_output(
            "docker",
            &["version", "--format", "{{.Server.Version}}"],
            Duration::from_secs(4),
        )
        .map(|o| o.status.success())
        .unwrap_or(false);
        if let Ok(mut cache) = self.hardware.lock() {
            *cache = HardwareSnapshot {
                gpus,
                sandbox_available,
            };
        }
    }

    pub async fn run_hardware_discovery(self: std::sync::Arc<Self>) {
        // First scan runs off the UI thread. Subsequent scans are deliberately
        // infrequent; status polling only reads this cache.
        loop {
            if self.shutting_down.load(Ordering::Acquire) {
                break;
            }
            let manager = self.clone();
            let _ = tokio::task::spawn_blocking(move || manager.refresh_hardware()).await;
            for _ in 0..60 {
                if self.shutting_down.load(Ordering::Acquire) {
                    return;
                }
                tokio::time::sleep(Duration::from_secs(1)).await;
            }
        }
    }
    pub fn config_view(&self) -> Result<NodeConfigView, String> {
        let c = self.cfg()?;
        Ok(NodeConfigView {
            enabled: c.enabled,
            allow_remote_workloads: c.allow_remote_workloads,
            allow_networked_inference: c.allow_networked_inference,
            max_cpu_percent: c.max_cpu_percent,
            max_memory_mb: c.max_memory_mb,
            gateway_url: c.gateway_url,
            ollama_url: c.ollama_url,
            trusted_scheduler_key_hex: c.trusted_scheduler_key_hex,
            allowed_images: c.allowed_images,
            registered: !c.node_token.is_empty(),
        })
    }
    pub fn public_identity(&self) -> Result<Value, String> {
        let kp = self.keypair()?;
        Ok(
            json!({"node_id":self.node_id()? ,"public_key_hex":hex::encode(kp.public_key().as_ref()),"algorithm":"Ed25519"}),
        )
    }
    pub async fn register(&self) -> Result<Value, String> {
        let cfg = self.cfg()?;
        if cfg.gateway_url.is_empty() {
            return Err("Configure an Atlas gateway URL before registration".into());
        }
        if !cfg.gateway_url.starts_with("https://")
            && !cfg.gateway_url.starts_with("http://127.0.0.1:")
            && !cfg.gateway_url.starts_with("http://localhost:")
        {
            return Err("Refusing to send node identity over an insecure remote connection".into());
        }
        let id = self.public_identity()?;
        let client = Self::http_client(15)?;
        let base = cfg.gateway_url.trim_end_matches('/');
        let challenge: Value = client
            .post(format!("{base}/v1/nodes/challenge"))
            .json(&json!({"node_id":id["node_id"],"public_key_hex":id["public_key_hex"]}))
            .send()
            .await
            .map_err(|e| format!("Gateway challenge request failed: {e}"))?
            .error_for_status()
            .map_err(|e| format!("Gateway challenge rejected: {e}"))?
            .json()
            .await
            .map_err(|e| format!("Invalid challenge response: {e}"))?;
        let nonce = challenge
            .get("challenge")
            .and_then(Value::as_str)
            .ok_or("Gateway did not provide a challenge")?;
        let kp = self.keypair()?;
        let signature = kp.sign(nonce.as_bytes());
        let response:Value=client.post(format!("{base}/v1/nodes/register")).json(&json!({"node_id":id["node_id"],"public_key_hex":id["public_key_hex"],"challenge":nonce,"signature_hex":hex::encode(signature.as_ref())})).send().await.map_err(|e|format!("Registration request failed: {e}"))?.error_for_status().map_err(|e|format!("Registration rejected: {e}"))?.json().await.map_err(|e|format!("Invalid registration response: {e}"))?;
        let token = response
            .get("node_token")
            .and_then(Value::as_str)
            .ok_or("Gateway response did not contain node_token")?
            .to_string();
        if token.len() < 32 {
            return Err("Gateway returned a node credential that is too short".into());
        }
        let mut next = cfg;
        next.node_token = token;
        self.save_config(next)?;
        Ok(
            json!({"registered":true,"node_id":id["node_id"],"message":"Node identity registered. Remote workloads remain disabled until explicitly enabled."}),
        )
    }
    pub fn set_enabled(&self, enabled: bool) -> Result<NodeStatus, String> {
        let mut c = self.cfg()?;
        c.enabled = enabled;
        if !enabled {
            c.allow_remote_workloads = false;
            c.allow_networked_inference = false
        }
        self.save_config(c)?;
        if !enabled {
            self.cancel_active_workload();
        }
        self.status()
    }
    pub fn update_policy(
        &self,
        allow_remote: bool,
        allow_networked: bool,
        cpu: u8,
        memory: u64,
    ) -> Result<NodeStatus, String> {
        let mut c = self.cfg()?;
        if allow_remote && !c.enabled {
            return Err("Enable the node before allowing remote workloads".into());
        }
        c.allow_remote_workloads = allow_remote;
        c.allow_networked_inference = allow_networked;
        c.max_cpu_percent = cpu;
        c.max_memory_mb = memory;
        self.save_config(c)?;
        if !allow_remote {
            self.cancel_active_workload();
        }
        self.status()
    }
    pub async fn local_models(&self) -> Result<Value, String> {
        let c = self.cfg()?;
        let client = Self::http_client(8)?;
        let base = c.ollama_url.trim_end_matches('/');
        let ollama = client.get(format!("{base}/api/tags")).send().await;
        if let Ok(r) = ollama {
            if r.status().is_success() {
                return r.json::<Value>().await.map_err(|e| e.to_string());
            }
        }
        let openai = client
            .get(format!("{base}/v1/models"))
            .send()
            .await
            .map_err(|e| {
                format!("Local model discovery failed for Ollama and OpenAI-compatible APIs: {e}")
            })?;
        if !openai.status().is_success() {
            return Err(format!(
                "Local inference endpoint returned HTTP {} for /v1/models",
                openai.status()
            ));
        }
        let v = openai.json::<Value>().await.map_err(|e| e.to_string())?;
        let models = v
            .get("data")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default()
            .into_iter()
            .filter_map(|m| {
                m.get("id")
                    .and_then(Value::as_str)
                    .map(|id| json!({"name":id}))
            })
            .collect::<Vec<_>>();
        Ok(json!({"models":models,"runtime":"openai-compatible"}))
    }
    pub async fn benchmark_local(&self, model: String, prompt: String) -> Result<Value, String> {
        let c = self.cfg()?;
        if model.trim().is_empty() {
            return Err("Choose a local model first".into());
        }
        let base = c.ollama_url.trim_end_matches('/');
        let client = Self::http_client(180)?;
        let ollama_start = Instant::now();
        let ollama = client
            .post(format!("{base}/api/generate"))
            .json(&json!({"model":model,"prompt":prompt,"stream":false,"keep_alive":"0"}))
            .send()
            .await;
        if let Ok(r) = ollama {
            if r.status().is_success() {
                let v = r.json::<Value>().await.map_err(|e| e.to_string())?;
                let wall_ms = ollama_start.elapsed().as_millis() as u64;
                return Ok(ollama_benchmark_result(&model, &v, wall_ms));
            }
        }
        // Start a distinct timer for fallback. A failed/slow Ollama probe must not
        // inflate the OpenAI-compatible request's reported latency or rate.
        let openai_start = Instant::now();
        let r = client
            .post(format!("{base}/v1/chat/completions"))
            .json(&json!({"model":model,"messages":[{"role":"user","content":prompt}],"max_tokens":128,"stream":false}))
            .send()
            .await
            .map_err(|e| {
                format!(
                    "Local benchmark request failed for Ollama and OpenAI-compatible APIs: {e}"
                )
            })?;
        let status = r.status();
        let v = r.json::<Value>().await.map_err(|e| e.to_string())?;
        if !status.is_success() {
            return Err(format!(
                "Local inference endpoint returned HTTP {status}: {v}"
            ));
        }
        let wall_ms = openai_start.elapsed().as_millis() as u64;
        Ok(openai_benchmark_result(&model, &v, wall_ms))
    }
    fn signed_request(
        &self,
        method: &str,
        path: &str,
        body: &[u8],
    ) -> Result<(String, String), String> {
        let timestamp = now();
        let body_hash = hex::encode(digest::digest(&digest::SHA256, body).as_ref());
        let message = format!("{timestamp}.{method}.{path}.{body_hash}");
        let sig = self.keypair()?.sign(message.as_bytes());
        Ok((timestamp.to_string(), hex::encode(sig.as_ref())))
    }
    async fn post_signed(
        &self,
        path: &str,
        body: Value,
        cfg: &NodeConfig,
    ) -> Result<reqwest::Response, String> {
        let raw = serde_json::to_vec(&body).map_err(|e| e.to_string())?;
        let (ts, sig) = self.signed_request("POST", path, &raw)?;
        Self::http_client(15)?
            .post(format!("{}{}", cfg.gateway_url.trim_end_matches('/'), path))
            .header("x-atlas-node-id", self.node_id()?)
            .header("x-atlas-timestamp", ts)
            .header("x-atlas-signature", sig)
            .bearer_auth(&cfg.node_token)
            .json(&body)
            .send()
            .await
            .map_err(|e| e.to_string())
    }
    async fn heartbeat(&self, cfg: &NodeConfig) -> Result<(), String> {
        let status = self.status()?;
        let body = json!({"node_id":status.node_id,"enabled":status.enabled,"cpu_percent":status.cpu_percent,"memory_total_mb":status.memory_total_mb,"memory_available_mb":status.memory_available_mb,"gpus":status.gpus,"remote_workloads_allowed":status.remote_workloads_allowed,"network_inference_allowed":cfg.allow_networked_inference&&cfg.enabled,"timestamp":now()});
        let r = self.post_signed("/v1/nodes/heartbeat", body, cfg).await?;
        if !r.status().is_success() {
            return Err(format!("Heartbeat rejected: HTTP {}", r.status()));
        }
        Ok(())
    }
    async fn claim_workload(&self, cfg: &NodeConfig) -> Result<Option<WorkloadEnvelope>, String> {
        let r = self
            .post_signed(
                "/v1/workloads/claim",
                json!({"node_id":self.node_id()?}),
                cfg,
            )
            .await?;
        if r.status() == reqwest::StatusCode::NO_CONTENT
            || r.status() == reqwest::StatusCode::NOT_FOUND
        {
            return Ok(None);
        }
        if !r.status().is_success() {
            return Err(format!("Workload claim rejected: HTTP {}", r.status()));
        }
        let v: Value = r.json().await.map_err(|e| e.to_string())?;
        let item = v.get("workload").cloned().unwrap_or(v);
        serde_json::from_value(item)
            .map(Some)
            .map_err(|e| format!("Invalid signed workload envelope: {e}"))
    }
    async fn upload_receipt(&self, cfg: &NodeConfig, receipt: Value) -> Result<(), String> {
        let r = self
            .post_signed("/v1/workloads/complete", json!({"receipt":receipt}), cfg)
            .await?;
        if !r.status().is_success() {
            return Err(format!("Receipt upload rejected: HTTP {}", r.status()));
        }
        Ok(())
    }
    pub async fn run_agent_loop(self: std::sync::Arc<Self>) {
        while !self.shutting_down.load(Ordering::Relaxed) {
            let cfg = self.cfg().ok();
            if let Some(cfg) = cfg {
                if cfg.enabled && !cfg.node_token.is_empty() && !cfg.gateway_url.is_empty() {
                    let _ = self.heartbeat(&cfg).await;
                    if cfg.allow_remote_workloads {
                        if let Ok(Some(workload)) = self.claim_workload(&cfg).await {
                            let this = self.clone();
                            if let Ok(Ok(receipt)) = tokio::task::spawn_blocking(move || {
                                this.execute_signed_workload(workload)
                            })
                            .await
                            {
                                let _ = self.upload_receipt(&cfg, receipt).await;
                            }
                        }
                    }
                }
            }
            tokio::time::sleep(std::time::Duration::from_secs(20)).await;
        }
    }
    pub fn shutdown(&self) {
        self.shutting_down.store(true, Ordering::Relaxed);
        self.cancel_active_workload();
    }
    fn cancel_active_workload(&self) {
        let cidfile = self.active_cidfile.lock().ok().and_then(|mut p| p.take());
        let mut id = self
            .active_container_id
            .lock()
            .ok()
            .and_then(|mut p| p.take());
        if id.is_none() {
            id = cidfile
                .as_ref()
                .and_then(|p| fs::read_to_string(p).ok())
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty());
        }
        if let Some(id) = id {
            let _ = hidden_command("docker")
                .args(["stop", "--time", "3", &id])
                .output();
        }
        if let Ok(mut active) = self.active_child.lock() {
            if let Some(mut child) = active.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
        if let Some(path) = cidfile {
            let _ = fs::remove_file(path);
        }
    }
    pub async fn network_status(&self) -> Result<Value, String> {
        let c = self.cfg()?;
        if c.gateway_url.is_empty() {
            return Ok(json!({"available":false,"reason":"Gateway URL is not configured"}));
        }
        let r = Self::http_client(8)?
            .get(format!(
                "{}/v1/network/status",
                c.gateway_url.trim_end_matches('/')
            ))
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if !r.status().is_success() {
            return Ok(
                json!({"available":false,"http_status":r.status().as_u16(),"reason":"Network status endpoint unavailable"}),
            );
        }
        Ok(json!({"available":true,"status":r.json::<Value>().await.map_err(|e|e.to_string())?}))
    }
    pub async fn submit_inference(
        &self,
        model: String,
        prompt: String,
        max_tokens: u32,
    ) -> Result<Value, String> {
        let c = self.cfg()?;
        if !c.enabled || !c.allow_networked_inference {
            return Err("Network inference is disabled. Enable the node and network-inference permission first.".into());
        }
        if c.node_token.is_empty() {
            return Err("Register this node with the Atlas gateway first".into());
        }
        if model.trim().is_empty() || prompt.trim().is_empty() {
            return Err("Model and prompt are required".into());
        }
        let body = json!({"model":model,"prompt":prompt,"max_tokens":max_tokens.clamp(1,8192)});
        let path = "/v1/inference";
        let r = self.post_signed(path, body, &c).await?;
        let status = r.status();
        let v = r.json::<Value>().await.unwrap_or_else(|_| json!({}));
        if !status.is_success() {
            return Err(format!(
                "Atlas inference gateway returned HTTP {status}: {v}"
            ));
        }
        Ok(v)
    }
    pub fn execute_signed_workload(&self, w: WorkloadEnvelope) -> Result<Value, String> {
        let c = self.cfg()?;
        if !c.enabled || !c.allow_remote_workloads {
            return Err("Remote workload execution is disabled by the device owner".into());
        }
        if w.expires_at_unix < now() {
            return Err("Workload authorization has expired".into());
        }
        if w.image.contains(":latest") || !w.image.contains("@sha256:") {
            return Err(
                "Only immutable container images pinned by SHA-256 digest are accepted".into(),
            );
        }
        if !c.allowed_images.iter().any(|i| i == &w.image) {
            return Err("Container image is not on this device's allowlist".into());
        }
        if w.command.is_empty() || w.command.len() > 64 {
            return Err("Invalid workload command".into());
        }
        let key = hex::decode(&c.trusted_scheduler_key_hex)
            .map_err(|_| "Trusted scheduler key is invalid")?;
        if key.len() != 32 {
            return Err("Trusted scheduler key must be a 32-byte Ed25519 public key".into());
        }
        let sig = hex::decode(&w.signature_hex).map_err(|_| "Workload signature is invalid")?;
        let canonical=serde_json::to_vec(&json!({"workload_id":&w.workload_id,"image":&w.image,"command":&w.command,"max_memory_mb":w.max_memory_mb,"max_cpu_percent":w.max_cpu_percent,"expires_at_unix":w.expires_at_unix,"nonce":w.nonce})).map_err(|e|e.to_string())?;
        UnparsedPublicKey::new(&ED25519, &key)
            .verify(&canonical, &sig)
            .map_err(|_| "Workload signature verification failed")?;
        self.reserve_workload(&w)?;
        let mem = w.max_memory_mb.min(c.max_memory_mb);
        let cpu = w.max_cpu_percent.min(c.max_cpu_percent).max(1);
        let started = now();
        let mem = mem.max(256);
        let cidfile = self.root.join(format!(
            "container-{}.cid",
            hex::encode(digest::digest(&digest::SHA256, w.workload_id.as_bytes()).as_ref())
        ));
        let mut docker = hidden_command("docker");
        docker
            .args(["run", "--rm", "--pull=never", "--cidfile"])
            .arg(&cidfile)
            .args([
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=128",
                "--memory",
            ])
            .arg(format!("{mem}m"))
            .args(["--memory-swap"])
            .arg(format!("{mem}m"))
            .args(["--cpus"])
            .arg(format!("{:.2}", cpu as f32 / 100.0))
            .args([
                "--user",
                "65532:65532",
                "--ulimit",
                "nofile=1024:1024",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=64m",
            ])
            .arg(&w.image)
            .args(&w.command)
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null());
        let mut active = self
            .active_child
            .lock()
            .map_err(|_| "Active workload lock poisoned")?;
        if active.is_some() {
            return Err("Another Atlas workload is already active on this node".into());
        }
        if let Ok(mut p) = self.active_cidfile.lock() {
            *p = Some(cidfile.clone());
        }
        let child = match docker.spawn() {
            Ok(child) => child,
            Err(e) => {
                if let Ok(mut p) = self.active_cidfile.lock() {
                    p.take();
                }
                let _ = fs::remove_file(&cidfile);
                return Err(format!("Docker sandbox could not start: {e}"));
            }
        };
        *active = Some(child);
        drop(active);
        let still_allowed = self
            .cfg()
            .map(|v| v.enabled && v.allow_remote_workloads)
            .unwrap_or(false);
        if !still_allowed {
            self.cancel_active_workload();
            return Err("Node consent was revoked before workload start".into());
        }
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(900);
        let mut timed_out = false;
        let exit_code = loop {
            if let Ok(id) = fs::read_to_string(&cidfile) {
                let id = id.trim().to_string();
                if !id.is_empty() {
                    if let Ok(mut current) = self.active_container_id.lock() {
                        *current = Some(id);
                    }
                }
            }
            let polled = {
                let mut active = self
                    .active_child
                    .lock()
                    .map_err(|_| "Active workload lock poisoned")?;
                match active.as_mut() {
                    Some(child) => match child.try_wait() {
                        Ok(Some(status)) => {
                            *active = None;
                            Some(Ok(status.code()))
                        }
                        Ok(None) => None,
                        Err(e) => Some(Err(e.to_string())),
                    },
                    None => Some(Ok(None)),
                }
            };
            if let Some(result) = polled {
                if let Ok(mut current) = self.active_container_id.lock() {
                    current.take();
                }
                if let Ok(mut p) = self.active_cidfile.lock() {
                    p.take();
                }
                let _ = fs::remove_file(&cidfile);
                break result?;
            }
            if std::time::Instant::now() >= deadline {
                timed_out = true;
                self.cancel_active_workload();
                let _ = fs::remove_file(&cidfile);
                break None;
            }
            std::thread::sleep(std::time::Duration::from_millis(250));
        };
        let elapsed = now().saturating_sub(started);
        let success = !timed_out && exit_code == Some(0);
        let state = if success {
            "executed_unverified"
        } else {
            "failed"
        };
        let mut receipt = json!({"workload_id":w.workload_id,"nonce":w.nonce,"node_id":self.node_id()?,"started_at_unix":started,"finished_at_unix":now(),"runtime_ms":elapsed*1000,"memory_limit_mb":mem,"cpu_limit_percent":cpu,"exit_code":exit_code,"timed_out":timed_out,"state":state,"verified":false});
        let signed = serde_json::to_vec(&receipt).map_err(|e| e.to_string())?;
        let signature = self.keypair()?.sign(&signed);
        receipt["node_signature_hex"] = json!(hex::encode(signature.as_ref()));
        self.append_ledger(&receipt)?;
        Ok(receipt)
    }
    fn reserve_workload(&self, w: &WorkloadEnvelope) -> Result<(), String> {
        let path = self.claims_path();
        let existing = fs::read_to_string(&path).unwrap_or_default();
        for line in existing.lines() {
            if let Ok(v) = serde_json::from_str::<Value>(line) {
                if v.get("workload_id").and_then(Value::as_str) == Some(w.workload_id.as_str())
                    || v.get("nonce").and_then(Value::as_str) == Some(w.nonce.as_str())
                {
                    return Err(
                        "Duplicate workload ID or nonce rejected (replay protection)".into(),
                    );
                }
            }
        }
        let mut f = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)
            .map_err(|e| e.to_string())?;
        use std::io::Write;
        writeln!(
            f,
            "{}",
            json!({"workload_id":w.workload_id,"nonce":w.nonce,"reserved_at_unix":now()})
        )
        .map_err(|e| e.to_string())?;
        f.sync_all().map_err(|e| e.to_string())
    }
    fn append_ledger(&self, record: &Value) -> Result<(), String> {
        let mut f = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.ledger_path())
            .map_err(|e| e.to_string())?;
        use std::io::Write;
        writeln!(f, "{}", record).map_err(|e| e.to_string())?;
        f.sync_all().map_err(|e| e.to_string())
    }
    pub fn ledger(&self) -> Value {
        let s = fs::read_to_string(self.ledger_path()).unwrap_or_default();
        let rows: Vec<Value> = s
            .lines()
            .filter_map(|l| serde_json::from_str(l).ok())
            .collect();
        json!({"entries":rows,"verification":"local execution receipts are unverified until a trusted platform verifier signs a settlement record"})
    }
}

fn ollama_benchmark_result(model: &str, response: &Value, wall_time_ms: u64) -> Value {
    let generated = response
        .get("eval_count")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let eval_ns = response
        .get("eval_duration")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let tokens_per_second = if eval_ns > 0 {
        generated as f64 / (eval_ns as f64 / 1_000_000_000.0)
    } else {
        0.0
    };
    json!({
        "model": model,
        "wall_time_ms": wall_time_ms,
        "prompt_tokens": response.get("prompt_eval_count"),
        "generated_tokens": generated,
        "tokens_per_second": tokens_per_second,
        "tokens_per_second_kind": "generation_only",
        "tokens_per_second_label": "Generation rate (Ollama eval duration)",
        "load_duration_ns": response.get("load_duration"),
        "prompt_eval_duration_ns": response.get("prompt_eval_duration"),
        "eval_duration_ns": response.get("eval_duration"),
        "runtime": "ollama",
        "benchmark_kind": "single local request; rate uses server-reported generation duration; not standardized"
    })
}

fn openai_benchmark_result(model: &str, response: &Value, wall_time_ms: u64) -> Value {
    let generated = response
        .pointer("/usage/completion_tokens")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let tokens_per_second = if wall_time_ms > 0 {
        generated as f64 / (wall_time_ms as f64 / 1000.0)
    } else {
        0.0
    };
    json!({
        "model": model,
        "wall_time_ms": wall_time_ms,
        "prompt_tokens": response.pointer("/usage/prompt_tokens"),
        "generated_tokens": generated,
        "tokens_per_second": tokens_per_second,
        "tokens_per_second_kind": "total_request_estimate",
        "tokens_per_second_label": "End-to-end estimate (includes load, prompt processing, and response)",
        "runtime": "openai-compatible",
        "benchmark_kind": "single local request; rate estimates generated tokens over total request time, not decode speed; not standardized"
    })
}

#[cfg(test)]
mod benchmark_tests {
    use super::{ollama_benchmark_result, openai_benchmark_result, NodeManager};
    use serde_json::json;
    use std::{
        io::{Read, Write},
        net::{TcpListener, TcpStream},
        path::PathBuf,
        thread,
        time::{Duration, SystemTime, UNIX_EPOCH},
    };

    fn temp_config(base_url: &str) -> (NodeManager, PathBuf) {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "atlas-benchmark-test-{}-{unique}",
            std::process::id()
        ));
        std::fs::create_dir_all(&root).unwrap();
        std::fs::write(
            root.join("node-config.json"),
            json!({"ollama_url":base_url}).to_string(),
        )
        .unwrap();
        (NodeManager::new(root.clone()), root)
    }

    fn read_request_path(stream: &mut TcpStream) -> String {
        let mut bytes = Vec::new();
        let mut byte = [0_u8; 1];
        while !bytes.ends_with(b"\r\n\r\n") {
            stream.read_exact(&mut byte).unwrap();
            bytes.push(byte[0]);
        }
        let headers = String::from_utf8_lossy(&bytes);
        let content_length = headers
            .lines()
            .filter_map(|line| line.split_once(':'))
            .find(|(name, _)| name.eq_ignore_ascii_case("content-length"))
            .and_then(|(_, value)| value.trim().parse::<usize>().ok())
            .unwrap_or(0);
        let mut body = vec![0_u8; content_length];
        stream.read_exact(&mut body).unwrap();
        headers
            .lines()
            .next()
            .unwrap_or_default()
            .split_whitespace()
            .nth(1)
            .unwrap_or_default()
            .to_string()
    }

    fn write_response(stream: &mut TcpStream, status: &str, body: &str) {
        write!(
            stream,
            "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        )
        .unwrap();
        stream.flush().unwrap();
    }

    #[test]
    fn ollama_result_preserves_load_prefill_and_generation_timings() {
        let response = json!({
            "prompt_eval_count": 12,
            "eval_count": 4,
            "load_duration": 100,
            "prompt_eval_duration": 200,
            "eval_duration": 2_000_000_000
        });
        let result = ollama_benchmark_result("model-a", &response, 900);

        assert_eq!(result["load_duration_ns"], 100);
        assert_eq!(result["prompt_eval_duration_ns"], 200);
        assert_eq!(result["eval_duration_ns"], 2_000_000_000_u64);
        assert_eq!(result["tokens_per_second_kind"], "generation_only");
        assert_eq!(result["tokens_per_second"], 2.0);
    }

    #[test]
    fn openai_result_labels_rate_as_end_to_end_estimate() {
        let result = openai_benchmark_result(
            "model-b",
            &json!({"usage":{"prompt_tokens":12,"completion_tokens":6}}),
            2_000,
        );

        assert_eq!(result["tokens_per_second_kind"], "total_request_estimate");
        assert!(result["tokens_per_second_label"]
            .as_str()
            .unwrap()
            .contains("End-to-end estimate"));
        assert_eq!(result["tokens_per_second"], 3.0);
    }

    #[test]
    fn fallback_timing_excludes_the_failed_ollama_attempt() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let (mut ollama, _) = listener.accept().unwrap();
            assert_eq!(read_request_path(&mut ollama), "/api/generate");
            thread::sleep(Duration::from_millis(500));
            write_response(&mut ollama, "404 Not Found", "{}");

            let (mut openai, _) = listener.accept().unwrap();
            assert_eq!(read_request_path(&mut openai), "/v1/chat/completions");
            write_response(
                &mut openai,
                "200 OK",
                r#"{"usage":{"prompt_tokens":2,"completion_tokens":3}}"#,
            );
        });
        let (manager, root) = temp_config(&format!("http://{address}"));
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        let result = runtime
            .block_on(manager.benchmark_local("model-c".into(), "hello".into()))
            .unwrap();
        server.join().unwrap();
        std::fs::remove_dir_all(root).unwrap();

        assert!(result["wall_time_ms"].as_u64().unwrap() < 350);
        assert_eq!(result["runtime"], "openai-compatible");
    }
}
fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}
fn hidden_output(program: &str, args: &[&str], timeout: Duration) -> Option<Output> {
    let mut child = hidden_command(program)
        .args(args)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;
    let deadline = Instant::now() + timeout;
    loop {
        match child.try_wait() {
            Ok(Some(_)) => return child.wait_with_output().ok(),
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(100)),
            _ => {
                // Only terminate the exact helper process created above.
                let _ = child.kill();
                let _ = child.wait();
                return None;
            }
        }
    }
}

fn detect_gpus() -> Vec<GpuInfo> {
    let mut out = Vec::new();

    // Keep detailed NVIDIA telemetry when nvidia-smi is installed.
    if let Some(o) = hidden_output(
        "nvidia-smi",
        &[
            "--query-gpu=name,memory.total,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        Duration::from_secs(4),
    ) {
        if o.status.success() {
            for line in String::from_utf8_lossy(&o.stdout).lines() {
                let p: Vec<_> = line.split(',').map(str::trim).collect();

                if p.len() >= 4 {
                    out.push(GpuInfo {
                        name: p[0].into(),
                        vendor: "NVIDIA".into(),
                        vram_total_mb: p[1].parse().ok(),
                        vram_free_mb: p[2].parse().ok(),
                        utilization_percent: p[3].parse().ok(),
                        source: "nvidia-smi".into(),
                    });
                }
            }
        }
    }

    #[cfg(windows)]
    {
        for gpu in detect_gpus_dxgi() {
            if let Some(existing) = out
                .iter_mut()
                .find(|g| g.name.eq_ignore_ascii_case(&gpu.name))
            {
                if existing.vram_total_mb.is_none() {
                    existing.vram_total_mb = gpu.vram_total_mb;
                }
            } else {
                out.push(gpu);
            }
        }
    }

    #[cfg(not(windows))]
    if out.is_empty() {
        if let Some(o) = hidden_output("rocm-smi", &["--showproductname"], Duration::from_secs(4)) {
            if o.status.success() {
                let text = String::from_utf8_lossy(&o.stdout);

                for line in text
                    .lines()
                    .filter(|l| l.to_ascii_lowercase().contains("card series"))
                {
                    out.push(GpuInfo {
                        name: line.split(':').last().unwrap_or(line).trim().into(),
                        vendor: "AMD".into(),
                        vram_total_mb: None,
                        vram_free_mb: None,
                        utilization_percent: None,
                        source: "rocm-smi (model only; VRAM telemetry unavailable)".into(),
                    });
                }
            }
        }
    }

    out
}

#[cfg(windows)]
fn detect_gpus_dxgi() -> Vec<GpuInfo> {
    use windows::Win32::Graphics::Dxgi::{CreateDXGIFactory1, IDXGIFactory1};

    let mut out = Vec::new();

    let factory: IDXGIFactory1 = match unsafe { CreateDXGIFactory1::<IDXGIFactory1>() } {
        Ok(factory) => factory,
        Err(_) => return out,
    };

    for index in 0..32u32 {
        let adapter = match unsafe { factory.EnumAdapters1(index) } {
            Ok(adapter) => adapter,
            Err(_) => break,
        };

        let desc = match unsafe { adapter.GetDesc1() } {
            Ok(desc) => desc,
            Err(_) => continue,
        };

        let name_end = desc
            .Description
            .iter()
            .position(|&c| c == 0)
            .unwrap_or(desc.Description.len());

        let name = String::from_utf16_lossy(&desc.Description[..name_end]);

        let vendor = match desc.VendorId {
            0x1002 => "AMD",
            0x10DE => "NVIDIA",
            0x8086 => "Intel",
            _ => continue,
        };

        if name.trim().is_empty() {
            continue;
        }

        let dedicated_bytes = desc.DedicatedVideoMemory as u64;

        let total_mb = if dedicated_bytes > 0 {
            Some(dedicated_bytes / (1024 * 1024))
        } else {
            None
        };

        out.push(GpuInfo {
            name,
            vendor: vendor.into(),
            vram_total_mb: total_mb,
            vram_free_mb: None,
            utilization_percent: None,
            source: "Windows DXGI adapter discovery; live utilisation unavailable".into(),
        });
    }

    out
}
