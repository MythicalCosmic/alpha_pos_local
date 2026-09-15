//! Contract with the 1.0.x `update_helper.ps1` that installs the bridge release.
//!
//! The old helper writes `update_pending.flag` containing the target version,
//! swaps folders, launches `AlphaPOS.exe` and waits (≤120 s) for the flag to be
//! deleted. It treats an early exit of the launched process as a failure and
//! rolls back. The new shell therefore must, on that first launch: stay the same
//! process, skip its own updater, and delete the flag only once the backend is
//! serving and only if the flag names the running version.

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
