//! Contract with the 1.0.x `update_helper.ps1` that installs the bridge release.
//!
//! The old helper writes `update_pending.flag` containing the target version,
//! swaps folders, launches `AlphaPOS.exe` and waits (≤120 s) for the flag to be
//! deleted. It treats an early exit of the launched process as a failure and
//! rolls back. The new shell therefore must, on that first launch: stay the same
//! process, skip its own updater, and delete the flag only once the backend is
//! serving and only if the flag names the running version.

use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::time::Duration;

pub const FLAG_NAME: &str = "update_pending.flag";
/// The old helper's forced-stop path finishes within this after it sees the
/// flag disappear; rollback files must survive until then.
pub const HELPER_SETTLE: Duration = Duration::from_secs(30);

/// `%LOCALAPPDATA%\AlphaPOS\update`, where 1.0.x keeps its update markers.
pub fn legacy_update_dir(data_dir: &Path) -> PathBuf {
    data_dir.join("update")
}

pub fn pending_flag_path(data_dir: &Path) -> PathBuf {
    legacy_update_dir(data_dir).join(FLAG_NAME)
}

pub fn read_flag(data_dir: &Path, running_version: &str) -> PendingFlag {
    classify(fs::read_to_string(pending_flag_path(data_dir)).ok().as_deref(), running_version)
}

/// The helper's rollback copy: `<parent>\.<install name>.previous`.
pub fn previous_install_dir(install_dir: &Path) -> Option<PathBuf> {
    let name = install_dir.file_name()?.to_str()?;
    Some(install_dir.parent()?.join(format!(".{name}.previous")))
}

/// Delete the flag, which is the old helper's health-confirmation signal.
/// Returns whether a flag was removed.
pub fn confirm(data_dir: &Path) -> io::Result<bool> {
    match fs::remove_file(pending_flag_path(data_dir)) {
        Ok(()) => Ok(true),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error),
    }
}

/// Remove the rollback copy and helper scripts after the helper has settled.
pub fn cleanup_leftovers(data_dir: &Path, install_dir: &Path) -> Vec<PathBuf> {
    let mut removed = Vec::new();
    if let Some(previous) = previous_install_dir(install_dir) {
        if previous.is_dir() && fs::remove_dir_all(&previous).is_ok() {
            removed.push(previous);
        }
    }
    if let Ok(entries) = fs::read_dir(legacy_update_dir(data_dir)) {
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().to_string();
            let helper_file = name.starts_with("update-helper-") && (name.ends_with(".ps1") || name.ends_with(".ready"));
            if helper_file && fs::remove_file(entry.path()).is_ok() {
                removed.push(entry.path());
            }
        }
    }
    removed
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PendingFlag {
    /// No flag: a normal launch.
    Absent,
    /// The helper is waiting for this exact version to confirm.
    MatchesRunning,
    /// Flag names another version (or is empty). Keep it for the helper's
    /// recovery policy; never confirm on its behalf.
    Mismatch(String),
}

impl PendingFlag {
    /// Any flag means an old helper may be watching this process.
    pub fn blocks_self_update(&self) -> bool {
        !matches!(self, PendingFlag::Absent)
    }

    /// Delete the flag (the helper's success signal) once the backend serves.
    pub fn should_confirm(&self) -> bool {
        matches!(self, PendingFlag::MatchesRunning)
    }
}

pub fn classify(contents: Option<&str>, running_version: &str) -> PendingFlag {
    match contents {
        None => PendingFlag::Absent,
        Some(raw) => {
            let applied = raw.trim().trim_start_matches('\u{feff}');
            if !applied.is_empty() && applied == running_version.trim() {
                PendingFlag::MatchesRunning
            } else {
                PendingFlag::Mismatch(applied.to_string())
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("alphapos-legacy-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn previous_install_dir_matches_the_helper_naming() {
        let install = Path::new("/users/kassa/AppData/Local/Programs/AlphaPOS");
        assert_eq!(
            previous_install_dir(install).unwrap(),
            Path::new("/users/kassa/AppData/Local/Programs/.AlphaPOS.previous")
        );
    }

    #[test]
    fn confirm_removes_only_an_existing_flag() {
        let data = scratch("confirm");
        assert!(!confirm(&data).unwrap());
        fs::create_dir_all(legacy_update_dir(&data)).unwrap();
        fs::write(pending_flag_path(&data), "1.1.0").unwrap();
        assert_eq!(read_flag(&data, "1.1.0"), PendingFlag::MatchesRunning);
        assert!(confirm(&data).unwrap());
        assert!(!pending_flag_path(&data).exists());
        assert_eq!(read_flag(&data, "1.1.0"), PendingFlag::Absent);
        let _ = fs::remove_dir_all(data);
    }

    #[test]
    fn cleanup_removes_rollback_copy_and_helper_files_only() {
        let root = scratch("cleanup");
        let data = root.join("AlphaPOS");
        let install = root.join("Programs").join("AlphaPOS");
        let previous = root.join("Programs").join(".AlphaPOS.previous");
        fs::create_dir_all(previous.join("_internal")).unwrap();
        fs::create_dir_all(&install).unwrap();
        fs::create_dir_all(legacy_update_dir(&data)).unwrap();
        for name in ["update-helper-1.ps1", "update-helper-1.ready", "update_state.json", "update-helper-notes.txt"] {
            fs::write(legacy_update_dir(&data).join(name), "x").unwrap();
        }

        let removed = cleanup_leftovers(&data, &install);

        assert_eq!(removed.len(), 3);
        assert!(!previous.exists());
        assert!(install.exists());
        assert!(legacy_update_dir(&data).join("update_state.json").exists());
        assert!(legacy_update_dir(&data).join("update-helper-notes.txt").exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn absent_flag_is_a_normal_launch() {
        let flag = classify(None, "1.1.0");
        assert_eq!(flag, PendingFlag::Absent);
        assert!(!flag.blocks_self_update());
        assert!(!flag.should_confirm());
    }

    #[test]
    fn matching_flag_is_confirmed_and_blocks_updates() {
        let flag = classify(Some("1.1.0\r\n"), "1.1.0");
        assert_eq!(flag, PendingFlag::MatchesRunning);
        assert!(flag.blocks_self_update());
        assert!(flag.should_confirm());
    }

    #[test]
    fn bom_prefixed_flag_still_matches() {
        assert_eq!(classify(Some("\u{feff}1.1.0"), "1.1.0"), PendingFlag::MatchesRunning);
    }

    #[test]
    fn mismatched_or_empty_flag_is_kept() {
        let other = classify(Some("1.1.1"), "1.1.0");
        assert_eq!(other, PendingFlag::Mismatch("1.1.1".into()));
        assert!(other.blocks_self_update());
        assert!(!other.should_confirm());

        let empty = classify(Some("  "), "1.1.0");
        assert_eq!(empty, PendingFlag::Mismatch(String::new()));
        assert!(!empty.should_confirm());
    }
}
