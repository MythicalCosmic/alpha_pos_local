//! Backend boot phases reported by `GET /lifecycle` (desktop/lifecycle.py).

use serde::Deserialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Phase {
    Booting,
    Database,
    Migrating,
    Serving,
    Stopping,
    Error,
}

impl Phase {
    pub fn is_serving(self) -> bool {
        matches!(self, Phase::Serving)
    }

    /// Short splash text key for the loader window.
    pub fn splash_key(self) -> &'static str {
        match self {
            Phase::Booting => "splash.starting",
            Phase::Database => "splash.database",
            Phase::Migrating => "splash.migrating",
            Phase::Serving => "splash.ready",
            Phase::Stopping => "splash.stopping",
            Phase::Error => "splash.retrying",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct Snapshot {
    pub phase: Phase,
    #[serde(default)]
    pub detail: String,
    pub pid: u32,
    #[serde(default)]
    pub shutdown_requested: bool,
}

pub fn parse(body: &[u8]) -> Result<Snapshot, serde_json::Error> {
    serde_json::from_slice(body)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_backend_snapshot() {
        let body = br#"{"ok": true, "phase": "migrating", "detail": "starting POS server",
            "updated_at": "2026-09-16T08:00:00+00:00", "pid": 4242, "shutdown_requested": false}"#;
        let snap = parse(body).unwrap();
        assert_eq!(snap.phase, Phase::Migrating);
        assert_eq!(snap.detail, "starting POS server");
        assert_eq!(snap.pid, 4242);
        assert!(!snap.phase.is_serving());
    }

    #[test]
    fn unknown_phase_is_rejected() {
        assert!(parse(br#"{"phase": "dancing", "pid": 1}"#).is_err());
    }

    #[test]
    fn every_phase_has_splash_text() {
        for phase in [Phase::Booting, Phase::Database, Phase::Migrating, Phase::Serving, Phase::Stopping, Phase::Error] {
            assert!(phase.splash_key().starts_with("splash."));
        }
    }
}
