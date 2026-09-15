//! Platform-neutral logic for the Alpha POS desktop shell.
//!
//! Everything here is pure and unit tested on any OS. The Tauri binary wires
//! these decisions to Windows processes, files and the network.

pub mod backoff;
pub mod legacy_update;
pub mod lifecycle;
pub mod paths;
pub mod ready;
pub mod update_policy;
