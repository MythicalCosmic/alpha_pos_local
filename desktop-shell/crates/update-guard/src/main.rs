//! `alphapos-update-guard`: installs a verified shell update, confirms the new
//! version starts, and reinstalls the last known good version if it does not.
//!
//!   alphapos-update-guard --shell-pid <pid> --install-dir <dir> --data-dir <dir>
//!       --installer <setup.exe> --signature <setup.exe.sig> --version <x.y.z>
//!       --from-version <x.y.z> [--lkg-installer <setup.exe> --lkg-signature <sig>]
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(windows)]
mod process;

use std::collections::HashMap;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};

// Most fields are only read by the Windows installer path.
#[cfg_attr(not(windows), allow(dead_code))]
struct Args {
    shell_pid: u32,
    install_dir: PathBuf,
    data_dir: PathBuf,
    installer: PathBuf,
    signature: PathBuf,
    version: String,
    from_version: String,
    lkg: Option<(PathBuf, PathBuf)>,
}

fn parse_args(argv: impl Iterator<Item = String>) -> Result<Args, String> {
    let mut map = HashMap::new();
    let mut iter = argv.skip(1);
    while let Some(key) = iter.next() {
        let Some(name) = key.strip_prefix("--") else { return Err(format!("unexpected argument {key}")) };
        let value = iter.next().ok_or_else(|| format!("missing value for {key}"))?;
        map.insert(name.to_string(), value);
    }
    let take = |name: &str| map.get(name).cloned().ok_or_else(|| format!("--{name} is required"));
    Ok(Args {
        shell_pid: take("shell-pid")?.parse().map_err(|_| "invalid --shell-pid".to_string())?,
        install_dir: take("install-dir")?.into(),
        data_dir: take("data-dir")?.into(),
        installer: take("installer")?.into(),
        signature: take("signature")?.into(),
        version: take("version")?,
        from_version: take("from-version")?,
        lkg: match (map.get("lkg-installer"), map.get("lkg-signature")) {
            (Some(i), Some(s)) => Some((i.into(), s.into())),
            _ => None,
        },
    })
}

fn log(data_dir: &Path, message: &str) {
    let dir = data_dir.join("logs");
    let _ = std::fs::create_dir_all(&dir);
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(dir.join("update-guard.log")) {
        let secs = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or_default();
        let _ = writeln!(file, "{secs} [{}] {message}", std::process::id());
    }
}

#[cfg(windows)]
fn main() {
    let args = match parse_args(std::env::args()) {
        Ok(args) => args,
        Err(error) => {
            eprintln!("{error}");
            std::process::exit(2);
        }
    };
    let code = process::run(&args, &|msg| log(&args.data_dir, msg));
    std::process::exit(code);
}

#[cfg(not(windows))]
fn main() {
    match parse_args(std::env::args()) {
        Ok(args) => {
            log(&args.data_dir, "update guard only runs on Windows");
            std::process::exit(3);
        }
        Err(error) => {
            eprintln!("{error}");
            std::process::exit(2);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn argv(items: &[&str]) -> impl Iterator<Item = String> {
        std::iter::once("guard".to_string()).chain(items.iter().map(|s| s.to_string()).collect::<Vec<_>>())
    }

    #[test]
    fn parses_required_and_optional_arguments() {
        let args = parse_args(argv(&[
            "--shell-pid", "42", "--install-dir", "C:/p", "--data-dir", "C:/d", "--installer", "C:/s.exe",
            "--signature", "C:/s.exe.sig", "--version", "1.1.1", "--from-version", "1.1.0",
            "--lkg-installer", "C:/lkg.exe", "--lkg-signature", "C:/lkg.exe.sig",
        ]))
        .unwrap();
        assert_eq!(args.shell_pid, 42);
        assert_eq!(args.version, "1.1.1");
        assert!(args.lkg.is_some());
    }

    #[test]
    fn rejects_missing_and_malformed_arguments() {
        assert!(parse_args(argv(&["--shell-pid", "x"])).is_err());
        assert!(parse_args(argv(&["positional"])).is_err());
        assert!(parse_args(argv(&["--shell-pid"])).is_err());
    }
}
