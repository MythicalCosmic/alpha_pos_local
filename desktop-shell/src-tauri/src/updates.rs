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
    let updater = app.updater_builder().timeout(update_policy::CHECK_BUDGET).build().ok()?;
    let update = match tauri::async_runtime::block_on(updater.check()) {
        Ok(Some(update)) => update,
        _ => return None,
    };
    let check = RemoteCheck::Available { version: update.version.clone() };
    match update_policy::after_check(&check, CURRENT_VERSION, blocked) {
        AfterCheck::Download { .. } => Some(update),
        AfterCheck::StartNormally => None,
    }
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
