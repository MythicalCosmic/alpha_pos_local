//! Discord-style updates: decide before the POS starts, download on the splash,
//! hand the verified installer to the guard, never restart mid-shift.

use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use alphapos_shell_core::legacy_update::PendingFlag;
use alphapos_shell_core::update_policy::{self, AfterCheck, RemoteCheck, StagedUpdate, StartupDecision, StartupInputs};
use alphapos_update::{
    confirm_marker, lkg_dir, promote_staged_to_lkg, read_installer_dir, staged_dir, state_path, update_dir,
    verify_signature, UpdateState, TRUSTED_PUBLIC_KEYS,
};
use serde::{Deserialize, Serialize};
use tauri::AppHandle;
use tauri_plugin_updater::{Update, UpdaterExt};

pub const CURRENT_VERSION: &str = env!("CARGO_PKG_VERSION");
pub const PUBKEY: &str = TRUSTED_PUBLIC_KEYS[0];
/// A full installer over a slow restaurant line may take a while.
const DOWNLOAD_TIMEOUT: Duration = Duration::from_secs(1800);
pub const BACKGROUND_CHECK_EVERY: Duration = Duration::from_secs(6 * 3600);

#[derive(Serialize, Deserialize)]
struct StagedMeta {
    version: String,
}

pub type Staged = alphapos_update::InstallerFiles;

pub fn find_staged(data_dir: &Path) -> Option<Staged> {
    read_installer_dir(&staged_dir(data_dir))
}

/// The last version that confirmed healthy here, if its installer still verifies.
pub fn find_lkg(data_dir: &Path) -> Option<Staged> {
    let lkg = read_installer_dir(&lkg_dir(data_dir))?;
    verify_staged(&lkg).then_some(lkg)
}

/// Re-verify on every use: the file on disk is not trusted just because the
/// plugin verified the download earlier.
pub fn verify_staged(staged: &Staged) -> bool {
    match (fs::read(&staged.installer), fs::read_to_string(&staged.signature)) {
        (Ok(bytes), Ok(signature)) => verify_signature(TRUSTED_PUBLIC_KEYS, &signature, &bytes).is_ok(),
        _ => false,
    }
}

pub fn discard_staged(data_dir: &Path) {
    let _ = fs::remove_dir_all(staged_dir(data_dir));
}

/// A staged, verified update that is newer than this build and not blocked.
pub fn installable_staged(data_dir: &Path) -> Option<Staged> {
    let staged = find_staged(data_dir)?;
    let state = UpdateState::load(&state_path(data_dir));
    let ok = update_policy::is_newer(&staged.version, CURRENT_VERSION)
        && !state.blocked_versions.iter().any(|v| v == &staged.version)
        && verify_staged(&staged);
    ok.then_some(staged)
}

pub fn stage(data_dir: &Path, version: &str, installer: &[u8], signature: &str) -> io::Result<Staged> {
    let dir = staged_dir(data_dir);
    let tmp = update_dir(data_dir).join("staged.tmp");
    let _ = fs::remove_dir_all(&tmp);
    fs::create_dir_all(&tmp)?;
    fs::write(tmp.join("setup.exe"), installer)?;
    fs::write(tmp.join("setup.exe.sig"), signature)?;
    let meta = serde_json::to_vec(&StagedMeta { version: version.to_string() }).map_err(io::Error::other)?;
    // meta.json last: a crash mid-write never looks like a complete stage.
    fs::write(tmp.join("meta.json"), meta)?;
    let _ = fs::remove_dir_all(&dir);
    fs::rename(&tmp, &dir)?;
    find_staged(data_dir).ok_or_else(|| io::Error::other("staged update missing after write"))
}

pub fn startup_decision(data_dir: &Path, legacy_flag: PendingFlag, post_update: bool) -> (StartupDecision, UpdateState) {
    let state = UpdateState::load(&state_path(data_dir));
    let staged = find_staged(data_dir).map(|s| StagedUpdate { signature_valid: verify_staged(&s), version: s.version });
    let decision = update_policy::decide(&StartupInputs {
        current_version: CURRENT_VERSION,
        legacy_flag,
        confirming_update: post_update,
        staged,
        blocked_versions: &state.blocked_versions,
    });
    (decision, state)
}

/// Ask the update server within the startup budget. `None` means start the
/// POS normally (offline, up to date, blocked or any error).
pub fn check_remote(app: &AppHandle, blocked: &[String]) -> Option<Update> {
    check_remote_within(app, blocked, update_policy::CHECK_BUDGET).ok().flatten()
}

/// Same as `check_remote` with an explicit budget; `Err` carries why the check
/// itself failed (offline, server error) for the panel.
pub fn check_remote_within(app: &AppHandle, blocked: &[String], budget: Duration) -> Result<Option<Update>, String> {
    let updater = app.updater_builder().timeout(budget).build().map_err(|e| e.to_string())?;
    let update = match tauri::async_runtime::block_on(updater.check()) {
        Ok(Some(update)) => update,
        Ok(None) => return Ok(None),
        Err(error) => return Err(error.to_string()),
    };
    let check = RemoteCheck::Available { version: update.version.clone() };
    Ok(match update_policy::after_check(&check, CURRENT_VERSION, blocked) {
        AfterCheck::Download { .. } => Some(update),
        AfterCheck::StartNormally => None,
    })
}

/// What the panel's Updates page shows, published by the shell in
/// `DATA\update\shell-status.json` (read by `desktop/bridge.py`).
#[derive(Serialize, Default)]
pub struct ShellStatus {
    pub staged_version: Option<String>,
    pub checking: bool,
    pub last_check_at: Option<String>,
    pub last_check_error: String,
    pub blocked_versions: Vec<String>,
    pub last_rollback: Option<serde_json::Value>,
}

static STATUS_LOCK: Mutex<()> = Mutex::new(());
static CHECKING: AtomicBool = AtomicBool::new(false);
static LAST_CHECK: Mutex<Option<(String, String)>> = Mutex::new(None);

/// Rewrite the status file from what is on disk now. `checked` records the
/// result of a check that just finished: `Ok(())` or the error text.
pub fn publish_status(data_dir: &Path, checked: Option<Result<(), String>>) {
    let _guard = STATUS_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    if let Some(result) = checked {
        *LAST_CHECK.lock().unwrap_or_else(|e| e.into_inner()) = Some((now_rfc3339(), result.err().unwrap_or_default()));
    }
    let state = UpdateState::load(&state_path(data_dir));
    let last = LAST_CHECK.lock().unwrap_or_else(|e| e.into_inner()).clone();
    let status = ShellStatus {
        staged_version: installable_staged(data_dir).map(|s| s.version),
        checking: CHECKING.load(Ordering::Relaxed),
        last_check_at: last.as_ref().map(|(at, _)| at.clone()),
        last_check_error: last.map(|(_, error)| error).unwrap_or_default(),
        blocked_versions: state.blocked_versions.clone(),
        last_rollback: state.last_rollback.as_ref().and_then(|r| serde_json::to_value(r).ok()),
    };
    let dir = update_dir(data_dir);
    let _ = fs::create_dir_all(&dir);
    let tmp = dir.join("shell-status.json.tmp");
    if let Ok(bytes) = serde_json::to_vec_pretty(&status) {
        if fs::write(&tmp, bytes).is_ok() {
            let _ = fs::rename(&tmp, dir.join("shell-status.json"));
        }
    }
}

/// "Check now" from the panel: look, download and stage in the background.
/// Never installs; returns immediately if a check is already running.
pub fn check_and_stage_in_background(app: AppHandle, data_dir: PathBuf) {
    if CHECKING.swap(true, Ordering::SeqCst) {
        return;
    }
    publish_status(&data_dir, None);
    let _ = std::thread::Builder::new().name("manual-update-check".into()).spawn(move || {
        let result = (|| -> Result<(), String> {
            if installable_staged(&data_dir).is_some() {
                return Ok(());
            }
            let state = UpdateState::load(&state_path(&data_dir));
            let Some(update) = check_remote_within(&app, &state.blocked_versions, Duration::from_secs(30))? else {
                return Ok(());
            };
            let progress = start_download(data_dir.clone(), update);
            while !progress.done.load(Ordering::Relaxed) {
                std::thread::sleep(Duration::from_millis(500));
            }
            let outcome = progress.result.lock().unwrap_or_else(|e| e.into_inner()).clone();
            outcome.unwrap_or(Ok(()))
        })();
        CHECKING.store(false, Ordering::SeqCst);
        publish_status(&data_dir, Some(result));
    });
}

/// UTC timestamp without a date/time dependency (the panel parses RFC 3339).
fn now_rfc3339() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    rfc3339(secs)
}

fn rfc3339(unix_secs: i64) -> String {
    let days = unix_secs.div_euclid(86_400);
    let secs_of_day = unix_secs.rem_euclid(86_400);
    // Civil-from-days (Howard Hinnant), valid for the proleptic Gregorian calendar.
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        secs_of_day / 3_600,
        (secs_of_day % 3_600) / 60,
        secs_of_day % 60,
    )
}

#[derive(Default)]
pub struct DownloadProgress {
    pub downloaded: AtomicU64,
    /// 0 while the server has not sent a length.
    pub total: AtomicU64,
    pub done: AtomicBool,
    pub result: Mutex<Option<Result<(), String>>>,
}

impl DownloadProgress {
    pub fn total(&self) -> Option<u64> {
        match self.total.load(Ordering::Relaxed) {
            0 => None,
            total => Some(total),
        }
    }
}

/// Download (signature-verified by the plugin) and stage in the background.
/// The task keeps running if the splash stops waiting for it.
pub fn start_download(data_dir: PathBuf, mut update: Update) -> Arc<DownloadProgress> {
    let progress = Arc::new(DownloadProgress::default());
    let shared = progress.clone();
    update.timeout = Some(DOWNLOAD_TIMEOUT);
    tauri::async_runtime::spawn(async move {
        let downloaded = update
            .download(
                |chunk, total| {
                    shared.downloaded.fetch_add(chunk as u64, Ordering::Relaxed);
                    if let Some(total) = total {
                        shared.total.store(total, Ordering::Relaxed);
                    }
                },
                || {},
            )
            .await;
        let result = downloaded
            .map_err(|e| e.to_string())
            .and_then(|bytes| stage(&data_dir, &update.version, &bytes, &update.signature).map(|_| ()).map_err(|e| e.to_string()));
        *shared.result.lock().unwrap() = Some(result);
        shared.done.store(true, Ordering::Relaxed);
    });
    progress
}

/// Copy the bundled guard out of the install folder and start it detached.
/// The caller must exit right after so the guard can replace the files.
pub fn launch_guard(data_dir: &Path, staged: &Staged) -> io::Result<()> {
    let exe = std::env::current_exe()?;
    let install_dir = exe.parent().ok_or_else(|| io::Error::other("install folder unknown"))?.to_path_buf();
    let bundled = install_dir.join("bin").join("alphapos-update-guard.exe");
    let guard_dir = update_dir(data_dir).join("guard");
    fs::create_dir_all(&guard_dir)?;
    let guard = guard_dir.join("alphapos-update-guard.exe");
    fs::copy(&bundled, &guard)?;

    // Reinstall target if the new version fails its health check.
    let lkg = find_lkg(data_dir).filter(|lkg| lkg.version != staged.version);
    let spawn = |flags: u32| {
        let mut command = std::process::Command::new(&guard);
        command
            .arg("--shell-pid")
            .arg(std::process::id().to_string())
            .arg("--install-dir")
            .arg(&install_dir)
            .arg("--data-dir")
            .arg(data_dir)
            .arg("--installer")
            .arg(&staged.installer)
            .arg("--signature")
            .arg(&staged.signature)
            .arg("--version")
            .arg(&staged.version)
            .arg("--from-version")
            .arg(CURRENT_VERSION)
            .current_dir(data_dir);
        if let Some(lkg) = &lkg {
            command.arg("--lkg-installer").arg(&lkg.installer).arg("--lkg-signature").arg(&lkg.signature);
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(flags);
        }
        #[cfg(not(windows))]
        let _ = flags;
        command.spawn()
    };
    const DETACHED_PROCESS: u32 = 0x0000_0008;
    const CREATE_BREAKAWAY_FROM_JOB: u32 = 0x0100_0000;
    // Break away from any job the shell was started in; fall back if not allowed.
    spawn(DETACHED_PROCESS | CREATE_BREAKAWAY_FROM_JOB).or_else(|_| spawn(DETACHED_PROCESS))?;
    Ok(())
}

/// The guard waits for this marker to accept the new version.
pub fn confirm_post_update(data_dir: &Path, version: &str) {
    let marker = confirm_marker(data_dir, version);
    if let Some(dir) = marker.parent() {
        let _ = fs::create_dir_all(dir);
    }
    let _ = fs::write(&marker, version);
    // Keep the installer that just proved healthy for future rollbacks.
    if !promote_staged_to_lkg(data_dir, version).unwrap_or(false)
        && find_staged(data_dir).map(|s| s.version == version).unwrap_or(false)
    {
        discard_staged(data_dir);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn formats_utc_timestamps() {
        assert_eq!(rfc3339(0), "1970-01-01T00:00:00Z");
        assert_eq!(rfc3339(951_782_400), "2000-02-29T00:00:00Z");
        assert_eq!(rfc3339(1_789_790_430), "2026-09-19T04:00:30Z");
    }
}
