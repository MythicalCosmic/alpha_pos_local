//! Ready file written atomically by the backend once its control server binds.

use serde::Deserialize;

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct ReadyFile {
    pub port: u16,
    pub pid: u32,
    pub version: String,
}

#[derive(Debug, PartialEq, Eq)]
pub enum ReadyError {
    Malformed(String),
    ZeroPort,
    /// Written by a different process (a stale file from an earlier backend).
    WrongPid { expected: u32, found: u32 },
}

pub fn parse(bytes: &[u8], expected_pid: Option<u32>) -> Result<ReadyFile, ReadyError> {
    let ready: ReadyFile = serde_json::from_slice(bytes).map_err(|e| ReadyError::Malformed(e.to_string()))?;
    if ready.port == 0 {
        return Err(ReadyError::ZeroPort);
    }
    if let Some(expected) = expected_pid {
        if ready.pid != expected {
            return Err(ReadyError::WrongPid { expected, found: ready.pid });
        }
    }
    Ok(ready)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_the_backend_payload() {
        let body = br#"{"port": 51234, "pid": 900, "version": "1.1.0", "written_at": "2026-09-16T08:00:00+00:00"}"#;
        let ready = parse(body, Some(900)).unwrap();
        assert_eq!(ready.port, 51234);
        assert_eq!(ready.version, "1.1.0");
    }

    #[test]
    fn rejects_stale_zero_and_garbage() {
        assert_eq!(
            parse(br#"{"port": 1, "pid": 5, "version": "1"}"#, Some(6)),
            Err(ReadyError::WrongPid { expected: 6, found: 5 })
        );
        assert_eq!(parse(br#"{"port": 0, "pid": 5, "version": "1"}"#, None), Err(ReadyError::ZeroPort));
        assert!(matches!(parse(b"{", None), Err(ReadyError::Malformed(_))));
    }
}
