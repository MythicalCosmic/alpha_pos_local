//! Windows path comparisons for "is this process running from the install dir".
//!
//! Before an installer runs, every process whose image lives under the install
//! directory must be gone, or Windows keeps its files locked. Paths reported by
//! the OS vary in case, separators and the `\\?\` long-path prefix.

pub fn normalize(path: &str) -> String {
    let mut p = path.trim().replace('/', "\\");
    for prefix in ["\\\\?\\UNC\\", "\\\\?\\", "\\??\\"] {
        if let Some(rest) = p.strip_prefix(prefix) {
            p = if prefix.ends_with("UNC\\") { format!("\\\\{rest}") } else { rest.to_string() };
            break;
        }
    }
    while p.len() > 3 && p.ends_with('\\') {
        p.pop();
    }
    p.to_lowercase()
}

/// True when `child` is `root` itself or anything inside it.
pub fn is_under(child: &str, root: &str) -> bool {
    let child = normalize(child);
    let root = normalize(root);
    if root.is_empty() {
        return false;
    }
    child == root || child.starts_with(&format!("{root}\\"))
}

#[cfg(test)]
mod tests {
    use super::*;

    const ROOT: &str = r"C:\Users\Kassa\AppData\Local\Programs\AlphaPOS";

    #[test]
    fn matches_case_insensitively_with_long_path_prefix() {
        assert!(is_under(r"\\?\c:\users\kassa\appdata\local\programs\alphapos\backend\_internal\pgsql\bin\postgres.exe", ROOT));
        assert!(is_under(r"C:/Users/Kassa/AppData/Local/Programs/AlphaPOS/AlphaPOS.exe", ROOT));
        assert!(is_under(ROOT, &format!("{ROOT}\\")));
    }

    #[test]
    fn sibling_folders_with_shared_prefix_do_not_match() {
        assert!(!is_under(r"C:\Users\Kassa\AppData\Local\Programs\AlphaPOS-old\AlphaPOS.exe", ROOT));
        assert!(!is_under(r"C:\Users\Kassa\AppData\Local\Programs\.AlphaPOS.previous\AlphaPOS.exe", ROOT));
        assert!(!is_under(r"C:\Users\Kassa\AppData\Local\AlphaPOS\pgdata\postmaster.pid", ROOT));
    }

    #[test]
    fn empty_root_never_matches() {
        assert!(!is_under(r"C:\anything.exe", ""));
    }

    #[test]
    fn drive_root_keeps_its_separator() {
        assert_eq!(normalize(r"C:\"), r"c:\");
    }
}
