//! Update installation guard logic shared by the shell and the guard binary.
//!
//! The Tauri updater plugin downloads and verifies installers, but its
//! `install()` starts the installer and exits immediately: nothing is left to
//! confirm that the new version actually starts or to roll back. The guard is a
//! tiny separate process that runs the NSIS installer passively, relaunches the
//! shell, waits for its health confirmation and reinstalls the last known good
//! version on failure.

use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use base64::Engine;
use serde::{Deserialize, Serialize};

/// Minisign public keys (Tauri updater format: base64 of the key file text)
/// accepted for installers. A list allows rotating the signing key.
pub const TRUSTED_PUBLIC_KEYS: &[&str] = &[
    // minisign key A20C07FC786EF2F4, generated 2026-09-16 (private key kept offline in update_keys/).
    "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IEEyMEMwN0ZDNzg2RUYyRjQKUldUMDhtNTQvQWNNb3BTRUFHQWpULzh1bUY5Z0RPdHdZOWFQelUrTmpVQkx1TENscW82OWE5VVEK",
];

pub const SHELL_EXIT_TIMEOUT: Duration = Duration::from_secs(60);
pub const INSTALL_TIMEOUT: Duration = Duration::from_secs(600);
/// How long a freshly installed version has to reach "serving". The first
/// launch after an update migrates the database and a slow till can need
/// minutes; running out blocks the version for good and rolls back.
pub const HEALTH_TIMEOUT: Duration = Duration::from_secs(420);

pub fn update_dir(data_dir: &Path) -> PathBuf {
    data_dir.join("update")
}

pub fn confirm_marker(data_dir: &Path, version: &str) -> PathBuf {
    update_dir(data_dir).join(format!("confirmed-{version}.ok"))
}

pub fn state_path(data_dir: &Path) -> PathBuf {
    update_dir(data_dir).join("shell-update-state.json")
}

/// Verified installer staged for the next update.
pub fn staged_dir(data_dir: &Path) -> PathBuf {
    update_dir(data_dir).join("staged")
}

/// Installer of the last version that confirmed healthy on this till.
pub fn lkg_dir(data_dir: &Path) -> PathBuf {
    update_dir(data_dir).join("lkg")
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InstallerFiles {
    pub version: String,
    pub installer: PathBuf,
    pub signature: PathBuf,
}

#[derive(Serialize, Deserialize)]
struct InstallerMeta {
    version: String,
}

/// Read a `setup.exe` + `setup.exe.sig` + `meta.json` folder (staged or lkg).
pub fn read_installer_dir(dir: &Path) -> Option<InstallerFiles> {
    let meta: InstallerMeta = serde_json::from_slice(&fs::read(dir.join("meta.json")).ok()?).ok()?;
    let installer = dir.join("setup.exe");
    let signature = dir.join("setup.exe.sig");
    (installer.is_file() && signature.is_file()).then_some(InstallerFiles { version: meta.version, installer, signature })
}

/// After `version` confirmed healthy, keep its staged installer as the
/// last-known-good copy (replacing the previous one). No download needed: the
/// staged installer is exactly what is now running.
pub fn promote_staged_to_lkg(data_dir: &Path, version: &str) -> io::Result<bool> {
    let staged = staged_dir(data_dir);
    match read_installer_dir(&staged) {
        Some(files) if files.version == version => {}
        _ => return Ok(false),
    }
    let lkg = lkg_dir(data_dir);
    if lkg.exists() {
        fs::remove_dir_all(&lkg)?;
    }
    fs::rename(&staged, &lkg)?;
    Ok(true)
}

/// NSIS arguments: passive progress UI, update mode, pinned install folder.
/// `/D=` must be last and unquoted. `/R` is deliberately omitted so the guard
/// launches the new shell itself and can watch it.
pub fn installer_args(install_dir: &Path) -> Vec<String> {
    vec!["/P".into(), "/UPDATE".into(), format!("/D={}", install_dir.display())]
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Rollback {
    pub from_version: String,
    pub to_version: String,
    pub reason: String,
    pub at_unix: u64,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct UpdateState {
    /// Versions that failed their health check on this till; never installed again.
    pub blocked_versions: Vec<String>,
    pub last_rollback: Option<Rollback>,
    /// Version installed by the guard and still waiting for its confirmation.
    pub pending_confirmation: Option<String>,
}

impl UpdateState {
    pub fn load(path: &Path) -> UpdateState {
        fs::read(path)
            .ok()
            .and_then(|bytes| serde_json::from_slice(&bytes).ok())
            .unwrap_or_default()
    }

    pub fn save(&self, path: &Path) -> io::Result<()> {
        if let Some(dir) = path.parent() {
            fs::create_dir_all(dir)?;
        }
        let tmp = path.with_extension("json.tmp");
        fs::write(&tmp, serde_json::to_vec_pretty(self).map_err(io::Error::other)?)?;
        fs::rename(tmp, path)
    }

    pub fn block(&mut self, version: &str) {
        if !self.blocked_versions.iter().any(|v| v == version) {
            self.blocked_versions.push(version.to_string());
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
pub enum SignatureError {
    NoTrustedKeys,
    Encoding(String),
    Invalid,
}

fn decode_b64_text(value: &str) -> Result<String, SignatureError> {
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(value.trim())
        .map_err(|e| SignatureError::Encoding(e.to_string()))?;
    String::from_utf8(bytes).map_err(|e| SignatureError::Encoding(e.to_string()))
}

/// Verify `data` against a Tauri `.sig` file using any trusted key.
pub fn verify_signature(trusted_keys: &[&str], sig_file: &str, data: &[u8]) -> Result<(), SignatureError> {
    if trusted_keys.is_empty() {
        return Err(SignatureError::NoTrustedKeys);
    }
    let signature_text = decode_b64_text(sig_file)?;
    let signature = minisign_verify::Signature::decode(&signature_text)
        .map_err(|e| SignatureError::Encoding(e.to_string()))?;
    for key in trusted_keys {
        let Ok(key_text) = decode_b64_text(key) else { continue };
        let Ok(public_key) = minisign_verify::PublicKey::decode(&key_text) else { continue };
        if public_key.verify(data, &signature, false).is_ok() {
            return Ok(());
        }
    }
    Err(SignatureError::Invalid)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HealthResult {
    Confirmed,
    Exited(Option<i32>),
    TimedOut,
}

/// Wait until the new shell writes its confirmation marker, exits, or the
/// timeout passes. Closures keep this testable without real processes.
pub fn wait_for_health(
    timeout: Duration,
    poll: Duration,
    mut confirmed: impl FnMut() -> bool,
    mut exited: impl FnMut() -> Option<Option<i32>>,
    mut sleep: impl FnMut(Duration),
    mut now: impl FnMut() -> Instant,
) -> HealthResult {
    let deadline = now() + timeout;
    loop {
        if confirmed() {
            return HealthResult::Confirmed;
        }
        if let Some(code) = exited() {
            // A marker written just before exiting still counts.
            return if confirmed() { HealthResult::Confirmed } else { HealthResult::Exited(code) };
        }
        if now() >= deadline {
            return HealthResult::TimedOut;
        }
        sleep(poll);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;

    #[test]
    fn installer_args_put_install_dir_last() {
        let args = installer_args(Path::new(r"C:\Users\Kassa\AppData\Local\Programs\AlphaPOS"));
        assert_eq!(args[0], "/P");
        assert_eq!(args[1], "/UPDATE");
        assert_eq!(args.last().unwrap(), r"/D=C:\Users\Kassa\AppData\Local\Programs\AlphaPOS");
        assert!(!args.iter().any(|a| a == "/R"));
    }

    #[test]
    fn state_round_trip_and_block_is_idempotent() {
        let dir = std::env::temp_dir().join(format!("alphapos-guard-test-{}", std::process::id()));
        let path = state_path(&dir);
        let mut state = UpdateState::default();
        state.block("1.1.2");
        state.block("1.1.2");
        state.pending_confirmation = Some("1.1.3".into());
        state.save(&path).unwrap();
        let loaded = UpdateState::load(&path);
        assert_eq!(loaded.blocked_versions, vec!["1.1.2".to_string()]);
        assert_eq!(loaded.pending_confirmation.as_deref(), Some("1.1.3"));
        let _ = fs::remove_dir_all(dir);
    }

    fn write_installer_dir(dir: &Path, version: &str) {
        fs::create_dir_all(dir).unwrap();
        fs::write(dir.join("setup.exe"), format!("MZ {version}")).unwrap();
        fs::write(dir.join("setup.exe.sig"), "sig").unwrap();
        fs::write(dir.join("meta.json"), format!("{{\"version\":\"{version}\"}}")).unwrap();
    }

    #[test]
    fn confirmed_staged_installer_becomes_last_known_good() {
        let data = std::env::temp_dir().join(format!("alphapos-lkg-{}", std::process::id()));
        let _ = fs::remove_dir_all(&data);
        write_installer_dir(&lkg_dir(&data), "1.1.0");
        write_installer_dir(&staged_dir(&data), "1.1.1");

        // A different version never replaces the last known good installer.
        assert!(!promote_staged_to_lkg(&data, "1.1.2").unwrap());
        assert_eq!(read_installer_dir(&lkg_dir(&data)).unwrap().version, "1.1.0");

        assert!(promote_staged_to_lkg(&data, "1.1.1").unwrap());
        let lkg = read_installer_dir(&lkg_dir(&data)).unwrap();
        assert_eq!(lkg.version, "1.1.1");
        assert_eq!(fs::read_to_string(lkg.installer).unwrap(), "MZ 1.1.1");
        assert!(!staged_dir(&data).exists());
        let _ = fs::remove_dir_all(data);
    }

    #[test]
    fn incomplete_installer_dirs_are_ignored() {
        let data = std::env::temp_dir().join(format!("alphapos-lkg-incomplete-{}", std::process::id()));
        let _ = fs::remove_dir_all(&data);
        write_installer_dir(&staged_dir(&data), "1.1.1");
        fs::remove_file(staged_dir(&data).join("setup.exe.sig")).unwrap();
        assert!(read_installer_dir(&staged_dir(&data)).is_none());
        assert!(!promote_staged_to_lkg(&data, "1.1.1").unwrap());
        let _ = fs::remove_dir_all(data);
    }

    #[test]
    fn corrupt_state_loads_as_default() {
        let dir = std::env::temp_dir().join(format!("alphapos-guard-corrupt-{}", std::process::id()));
        let path = state_path(&dir);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, b"{not json").unwrap();
        assert_eq!(UpdateState::load(&path), UpdateState::default());
        let _ = fs::remove_dir_all(dir);
    }

    // Signed with the real updater key: `cargo tauri signer sign fixture.bin`.
    const FIXTURE_DATA: &[u8] = b"Alpha POS signature fixture v1\n";
    const FIXTURE_SIG: &str = "dW50cnVzdGVkIGNvbW1lbnQ6IHNpZ25hdHVyZSBmcm9tIHRhdXJpIHNlY3JldCBrZXkKUlVUMDhtNTQvQWNNb2pjOStObHM2anA1MldhaGRJV2RlMHpjck9tR0pGcGptbkVTcmdYSC95WjhVbVBESTJKcFUzQ1o0R05SUGhsMU5qMndEcTNmaEUyTWZtcXVUMi85cGdFPQp0cnVzdGVkIGNvbW1lbnQ6IHRpbWVzdGFtcDoxNzg5NTA5ODU3CWZpbGU6Zml4dHVyZS5iaW4KZmFqR0hVd3ZGYld3UkxrQ2xkS1RSWlo0NHRTdzJSTHEzUTdqeXlGN3RvRTFYQ002TU5aVUhKSmMzQXZ0Qll3VGp0Uk1NMjI4WU5JNmFhSG1HcEVaQlE9PQo=";

    #[test]
    fn real_updater_signature_verifies_and_tampering_is_rejected() {
        assert_eq!(verify_signature(TRUSTED_PUBLIC_KEYS, FIXTURE_SIG, FIXTURE_DATA), Ok(()));
        assert_eq!(
            verify_signature(TRUSTED_PUBLIC_KEYS, FIXTURE_SIG, b"Alpha POS signature fixture v2\n"),
            Err(SignatureError::Invalid)
        );
        // A garbage key is skipped; with no other key the signature is invalid.
        assert_eq!(verify_signature(&["bm90IGEga2V5"], FIXTURE_SIG, FIXTURE_DATA), Err(SignatureError::Invalid));
        // Key rotation: an extra untrusted entry must not block the real key.
        assert_eq!(
            verify_signature(&["bm90IGEga2V5", TRUSTED_PUBLIC_KEYS[0]], FIXTURE_SIG, FIXTURE_DATA),
            Ok(())
        );
    }

    #[test]
    fn signature_requires_trusted_keys_and_valid_encoding() {
        assert_eq!(verify_signature(&[], "x", b"data"), Err(SignatureError::NoTrustedKeys));
        assert!(matches!(verify_signature(&["a2V5"], "***not base64***", b"data"), Err(SignatureError::Encoding(_))));
    }

    #[test]
    fn health_confirmed_exited_and_timeout() {
        let clock = Cell::new(Instant::now());
        let advance = |d: Duration| clock.set(clock.get() + d);

        let polls = Cell::new(0);
        let result = wait_for_health(
            Duration::from_secs(10),
            Duration::from_secs(1),
            || {
                polls.set(polls.get() + 1);
                polls.get() > 3
            },
            || None,
            advance,
            || clock.get(),
        );
        assert_eq!(result, HealthResult::Confirmed);

        let result = wait_for_health(Duration::from_secs(10), Duration::from_secs(1), || false, || Some(Some(1)), advance, || clock.get());
        assert_eq!(result, HealthResult::Exited(Some(1)));

        let result = wait_for_health(Duration::from_secs(5), Duration::from_secs(1), || false, || None, advance, || clock.get());
        assert_eq!(result, HealthResult::TimedOut);
    }

    #[test]
    fn marker_written_right_before_exit_counts() {
        let calls = Cell::new(0);
        let result = wait_for_health(
            Duration::from_secs(5),
            Duration::from_millis(1),
            || {
                calls.set(calls.get() + 1);
                calls.get() >= 2
            },
            || Some(Some(0)),
            |_| {},
            Instant::now,
        );
        assert_eq!(result, HealthResult::Confirmed);
    }
}
