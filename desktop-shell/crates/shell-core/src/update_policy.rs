//! Startup update decisions (Discord-style, never mid-shift).
//!
//! The backend is not started until this decision is made, so installing at
//! startup never has to stop a running POS.

use std::time::Duration;

use semver::Version;

use crate::legacy_update::PendingFlag;

/// Total time the startup check may take before the POS starts normally.
pub const CHECK_BUDGET: Duration = Duration::from_secs(4);
/// Watch the download this long before estimating the remaining time.
pub const ETA_SAMPLE: Duration = Duration::from_secs(2);
/// Downloads expected to finish within this are awaited on the splash.
pub const FOREGROUND_ETA: Duration = Duration::from_secs(20);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StagedUpdate {
    pub version: String,
    /// Result of re-verifying the staged installer's signature right now.
    pub signature_valid: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StartupInputs<'a> {
    pub current_version: &'a str,
    pub legacy_flag: PendingFlag,
    /// A previous update is still waiting for this launch to confirm health.
    pub confirming_update: bool,
    pub staged: Option<StagedUpdate>,
    pub blocked_versions: &'a [String],
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SkipReason {
    LegacyHelperWaiting,
    ConfirmingUpdate,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StartupDecision {
    /// Start the POS right away; no network, no install.
    StartWithoutUpdates(SkipReason),
    /// A verified newer installer is already on disk: install now (seconds).
    InstallStaged { version: String },
    /// Ask the update server within [`CHECK_BUDGET`]. `discard_staged` removes
    /// an invalid, old or blocked staged installer first.
    CheckRemote { discard_staged: bool },
}

pub fn is_newer(candidate: &str, current: &str) -> bool {
    match (Version::parse(candidate.trim()), Version::parse(current.trim())) {
        (Ok(candidate), Ok(current)) => candidate > current,
        _ => false,
    }
}

fn is_blocked(version: &str, blocked: &[String]) -> bool {
    blocked.iter().any(|b| b.trim() == version.trim())
}

pub fn decide(inputs: &StartupInputs<'_>) -> StartupDecision {
    if inputs.legacy_flag.blocks_self_update() {
        return StartupDecision::StartWithoutUpdates(SkipReason::LegacyHelperWaiting);
    }
    if inputs.confirming_update {
        return StartupDecision::StartWithoutUpdates(SkipReason::ConfirmingUpdate);
    }
    match &inputs.staged {
        Some(staged)
            if staged.signature_valid
                && is_newer(&staged.version, inputs.current_version)
                && !is_blocked(&staged.version, inputs.blocked_versions) =>
        {
            StartupDecision::InstallStaged { version: staged.version.clone() }
        }
        Some(_) => StartupDecision::CheckRemote { discard_staged: true },
        None => StartupDecision::CheckRemote { discard_staged: false },
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RemoteCheck {
    /// Offline, timed out, bad signature or server error.
    Failed,
    UpToDate,
    Available { version: String },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AfterCheck {
    StartNormally,
    Download { version: String },
}

pub fn after_check(check: &RemoteCheck, current: &str, blocked: &[String]) -> AfterCheck {
    match check {
        RemoteCheck::Available { version } if is_newer(version, current) && !is_blocked(version, blocked) => {
            AfterCheck::Download { version: version.clone() }
        }
        _ => AfterCheck::StartNormally,
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DownloadMode {
    /// Still sampling the transfer rate.
    KeepWaiting,
    /// Finish on the splash, then install and relaunch.
    Foreground,
    /// Start the POS now; keep downloading and install on the next launch or
    /// when the operator presses "Restart to update".
    Background,
}

pub fn download_mode(downloaded: u64, total: Option<u64>, elapsed: Duration) -> DownloadMode {
    let Some(total) = total.filter(|t| *t > 0) else {
        return if elapsed >= ETA_SAMPLE { DownloadMode::Background } else { DownloadMode::KeepWaiting };
    };
    if downloaded >= total {
        return DownloadMode::Foreground;
    }
    if elapsed < ETA_SAMPLE {
        return DownloadMode::KeepWaiting;
    }
    let secs = elapsed.as_secs_f64();
    if downloaded == 0 || secs <= 0.0 {
        return DownloadMode::Background;
    }
    let rate = downloaded as f64 / secs;
    let eta = (total - downloaded) as f64 / rate;
    if eta <= FOREGROUND_ETA.as_secs_f64() {
        DownloadMode::Foreground
    } else {
        DownloadMode::Background
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn inputs(staged: Option<StagedUpdate>) -> StartupInputs<'static> {
        StartupInputs {
            current_version: "1.1.0",
            legacy_flag: PendingFlag::Absent,
            confirming_update: false,
            staged,
            blocked_versions: &[],
        }
    }

    fn staged(version: &str, signature_valid: bool) -> Option<StagedUpdate> {
        Some(StagedUpdate { version: version.into(), signature_valid })
    }

    #[test]
    fn legacy_helper_flag_skips_every_update_step() {
        let mut i = inputs(staged("1.2.0", true));
        i.legacy_flag = PendingFlag::MatchesRunning;
        assert_eq!(decide(&i), StartupDecision::StartWithoutUpdates(SkipReason::LegacyHelperWaiting));
        i.legacy_flag = PendingFlag::Mismatch("1.0.46".into());
        assert_eq!(decide(&i), StartupDecision::StartWithoutUpdates(SkipReason::LegacyHelperWaiting));
    }

    #[test]
    fn confirming_update_skips_updates() {
        let mut i = inputs(None);
        i.confirming_update = true;
        assert_eq!(decide(&i), StartupDecision::StartWithoutUpdates(SkipReason::ConfirmingUpdate));
    }

    #[test]
    fn valid_newer_staged_installer_installs() {
        assert_eq!(decide(&inputs(staged("1.1.1", true))), StartupDecision::InstallStaged { version: "1.1.1".into() });
    }

    #[test]
    fn invalid_old_or_blocked_staged_installer_is_discarded() {
        assert_eq!(decide(&inputs(staged("1.1.1", false))), StartupDecision::CheckRemote { discard_staged: true });
        assert_eq!(decide(&inputs(staged("1.1.0", true))), StartupDecision::CheckRemote { discard_staged: true });
        assert_eq!(decide(&inputs(staged("garbage", true))), StartupDecision::CheckRemote { discard_staged: true });
        let blocked = vec!["1.1.1".to_string()];
        let mut i = inputs(staged("1.1.1", true));
        i.blocked_versions = &blocked;
        assert_eq!(decide(&i), StartupDecision::CheckRemote { discard_staged: true });
    }

    #[test]
    fn no_staged_installer_checks_remote() {
        assert_eq!(decide(&inputs(None)), StartupDecision::CheckRemote { discard_staged: false });
    }

    #[test]
    fn remote_results() {
        let none: Vec<String> = vec![];
        assert_eq!(after_check(&RemoteCheck::Failed, "1.1.0", &none), AfterCheck::StartNormally);
        assert_eq!(after_check(&RemoteCheck::UpToDate, "1.1.0", &none), AfterCheck::StartNormally);
        assert_eq!(
            after_check(&RemoteCheck::Available { version: "1.2.0".into() }, "1.1.0", &none),
            AfterCheck::Download { version: "1.2.0".into() }
        );
        assert_eq!(after_check(&RemoteCheck::Available { version: "1.0.9".into() }, "1.1.0", &none), AfterCheck::StartNormally);
        let blocked = vec!["1.2.0".to_string()];
        assert_eq!(after_check(&RemoteCheck::Available { version: "1.2.0".into() }, "1.1.0", &blocked), AfterCheck::StartNormally);
    }

    #[test]
    fn prerelease_versions_compare_correctly() {
        assert!(is_newer("1.1.1", "1.1.1-rc.1"));
        assert!(!is_newer("1.1.1-rc.1", "1.1.1"));
    }

    #[test]
    fn download_mode_by_eta() {
        let s = Duration::from_secs;
        assert_eq!(download_mode(10, Some(100), s(1)), DownloadMode::KeepWaiting);
        // 50 MB of 80 MB in 2 s -> ETA 1.2 s.
        assert_eq!(download_mode(50_000_000, Some(80_000_000), s(2)), DownloadMode::Foreground);
        // 1 MB of 80 MB in 2 s -> ETA 158 s.
        assert_eq!(download_mode(1_000_000, Some(80_000_000), s(2)), DownloadMode::Background);
        assert_eq!(download_mode(0, Some(80_000_000), s(3)), DownloadMode::Background);
        assert_eq!(download_mode(80_000_000, Some(80_000_000), s(1)), DownloadMode::Foreground);
        assert_eq!(download_mode(5, None, s(1)), DownloadMode::KeepWaiting);
        assert_eq!(download_mode(5, None, s(2)), DownloadMode::Background);
    }
}
