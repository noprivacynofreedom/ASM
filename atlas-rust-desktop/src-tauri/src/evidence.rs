use serde::Serialize;
use std::time::{SystemTime, UNIX_EPOCH};
#[derive(Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceState {
    ExecutedUnverified,
    Failed,
}
#[derive(Serialize)]
pub struct EvidenceRecord {
    pub id: String,
    pub tool: String,
    pub state: EvidenceState,
    pub summary: String,
    pub timestamp_ms: u128,
    pub verified_by: Option<String>,
}
// Crucial: execution alone can NEVER create VERIFIED. A separate verifier command must do that.
pub fn record_execution(tool: &str, ok: bool, summary: &str) -> EvidenceRecord {
    let ts = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    EvidenceRecord {
        id: format!("tool-{ts}"),
        tool: tool.into(),
        state: if ok {
            EvidenceState::ExecutedUnverified
        } else {
            EvidenceState::Failed
        },
        summary: summary.into(),
        timestamp_ms: ts,
        verified_by: None,
    }
}
