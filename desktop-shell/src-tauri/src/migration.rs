//! First launch after the 1.0.x tufup updater installed this shell.
//!
//! The old `update_helper.ps1` watches the `AlphaPOS.exe` it launched and waits
//! up to 120 s for `update_pending.flag` to disappear; otherwise it rolls back.
//! Delete the flag only once the backend is really serving, then remove the
//! rollback copy after the helper has had time to settle.

use std::path::PathBuf;

use alphapos_shell_core::legacy_update::{self, PendingFlag};

use crate::backend;

pub struct LegacyHandshake {
    flag: PendingFlag,
    data_dir: PathBuf,
}

impl LegacyHandshake {
    pub fn detect() -> Self {
        let data_dir = backend::data_dir();
        let flag = legacy_update::read_flag(&data_dir, env!("CARGO_PKG_VERSION"));
        Self { flag, data_dir }
    }

    /// While an old helper may be watching, the shell must not update itself.
    #[allow(dead_code)]
    pub fn blocks_self_update(&self) -> bool {
        self.flag.blocks_self_update()
    }

    /// Call only after the backend reported `serving`.
    pub fn confirm_serving(&self) {
        if !self.flag.should_confirm() {
            return;
        }
        if legacy_update::confirm(&self.data_dir).is_err() {
            // Keep the old helper's rollback protection intact.
            return;
        }
        let data_dir = self.data_dir.clone();
        std::thread::spawn(move || {
            std::thread::sleep(legacy_update::HELPER_SETTLE);
            if let Some(install_dir) = std::env::current_exe().ok().and_then(|exe| exe.parent().map(|p| p.to_path_buf())) {
                legacy_update::cleanup_leftovers(&data_dir, &install_dir);
            }
        });
    }
}
