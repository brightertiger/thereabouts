//! Shared file-lease wire format and recovery naming; hosts probe PID liveness.
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

/// Bound all lock-file reads before parsing untrusted store state.
pub const MAX_BYTES: u64 = 1024;
/// Allow the creator to finish writing its tiny record before reclaiming an incomplete file.
pub const PARTIAL_GRACE_MS: u64 = 30_000;
/// Bound recovery nesting if processes repeatedly die while recovering a prior lease.
pub const MAX_RECOVERY_DEPTH: u8 = 8;

/// One immutable incarnation, written only after `O_EXCL` creation succeeds.
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Lease {
    /// Positive OS process id; a live owner never expires merely because it is old.
    pub pid: u32,
    /// Unix milliseconds for diagnostics and cross-host inspection.
    pub created_ms: u64,
    /// Unique 128-bit hexadecimal incarnation identity; not an authentication secret.
    pub token: String,
}
/// PID probing is host-owned. An incomplete recent record must not be stolen.
#[derive(Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum State {
    /// The host must probe this PID, treating permission errors as alive.
    Owner {
        /// OS process ID to probe without sending a signal.
        pid: u32,
    },
    /// Creation may still be in progress or the clock moved backwards.
    Pending,
    /// An incomplete record outlived the creation grace period.
    Abandoned,
}
/// Classify only the wire record; no filesystem or process access occurs here.
#[must_use]
pub fn state(contents: &str, modified_ms: u64, now_ms: u64) -> State {
    if let Ok(lease) = serde_json::from_str::<Lease>(contents)
        && lease.pid > 0
        && lease.pid <= i32::MAX.cast_unsigned()
        && lease.created_ms <= 9_007_199_254_740_991
        && lease.token.len() == 32
        && lease.token.bytes().all(|b| b.is_ascii_hexdigit())
    {
        return State::Owner { pid: lease.pid };
    }
    if now_ms.saturating_sub(modified_ms) >= PARTIAL_GRACE_MS {
        State::Abandoned
    } else {
        State::Pending
    }
}
/// Serialize takeover attempts for this exact record, including recovery of dead reapers.
#[must_use]
pub fn recovery_name(name: &str, contents: &str) -> String {
    let hash = Sha256::digest(format!("{name}\0{contents}").as_bytes());
    format!(".lock-reap-{hash:x}")
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn time_only_expires_incomplete_records() {
        assert_eq!(state("", 0, PARTIAL_GRACE_MS - 1), State::Pending);
        assert_eq!(state("", 0, PARTIAL_GRACE_MS), State::Abandoned);
        assert_eq!(state("{", 100, 1), State::Pending);
        let bytes = serde_json::to_string(&Lease {
            pid: 42,
            created_ms: 1,
            token: "a".repeat(32),
        })
        .unwrap();
        assert_eq!(state(&bytes, 0, u64::MAX), State::Owner { pid: 42 });
        assert_ne!(recovery_name(".lock", &bytes), recovery_name(".lock", ""));
    }
}
