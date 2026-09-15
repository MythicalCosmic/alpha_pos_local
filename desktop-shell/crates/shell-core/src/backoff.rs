//! Backend crash restarts with exponential backoff and a circuit breaker.

use std::collections::VecDeque;
use std::time::Duration;

pub const FIRST_DELAY: Duration = Duration::from_secs(2);
pub const MAX_DELAY: Duration = Duration::from_secs(60);
pub const CRASH_LIMIT: usize = 5;
pub const CRASH_WINDOW: Duration = Duration::from_secs(600);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Verdict {
    /// Restart the backend after this delay.
    Restart(Duration),
    /// Too many crashes in the window: stop and show the error screen.
    GiveUp,
}

/// Tracks unexpected backend exits. Timestamps are durations since the shell
/// started so tests do not depend on the wall clock.
#[derive(Debug, Clone)]
pub struct CrashBreaker {
    limit: usize,
    window: Duration,
    crashes: VecDeque<Duration>,
}

impl Default for CrashBreaker {
    fn default() -> Self {
        Self::new(CRASH_LIMIT, CRASH_WINDOW)
    }
}

impl CrashBreaker {
    pub fn new(limit: usize, window: Duration) -> Self {
        Self { limit, window, crashes: VecDeque::new() }
    }

    /// Record a crash at `at` and decide what to do next.
    pub fn record(&mut self, at: Duration) -> Verdict {
        while let Some(&oldest) = self.crashes.front() {
            if at.saturating_sub(oldest) > self.window {
                self.crashes.pop_front();
            } else {
                break;
            }
        }
        self.crashes.push_back(at);
        let recent = self.crashes.len();
        if recent >= self.limit {
            return Verdict::GiveUp;
        }
        Verdict::Restart(delay_for(recent))
    }

    /// Manual "Retry" from the error screen starts a fresh window.
    pub fn reset(&mut self) {
        self.crashes.clear();
    }

    pub fn recent_crashes(&self) -> usize {
        self.crashes.len()
    }
}

/// 2 s, 4 s, 8 s ... capped at 60 s for the n-th recent crash (1-based).
pub fn delay_for(recent_crashes: usize) -> Duration {
    let exponent = recent_crashes.saturating_sub(1).min(16) as u32;
    let delay = FIRST_DELAY.saturating_mul(1u32 << exponent);
    delay.min(MAX_DELAY)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn secs(s: u64) -> Duration {
        Duration::from_secs(s)
    }

    #[test]
    fn delays_grow_and_cap() {
        assert_eq!(delay_for(1), secs(2));
        assert_eq!(delay_for(2), secs(4));
        assert_eq!(delay_for(3), secs(8));
        assert_eq!(delay_for(6), secs(60));
        assert_eq!(delay_for(100), secs(60));
    }

    #[test]
    fn gives_up_after_limit_within_window() {
        let mut breaker = CrashBreaker::default();
        for i in 0..4 {
            assert!(matches!(breaker.record(secs(i * 10)), Verdict::Restart(_)));
        }
        assert_eq!(breaker.record(secs(50)), Verdict::GiveUp);
    }

    #[test]
    fn old_crashes_fall_out_of_the_window() {
        let mut breaker = CrashBreaker::default();
        for i in 0..4 {
            breaker.record(secs(i));
        }
        // Ten minutes later only this crash counts.
        assert_eq!(breaker.record(secs(1000)), Verdict::Restart(secs(2)));
        assert_eq!(breaker.recent_crashes(), 1);
    }

    #[test]
    fn reset_clears_history() {
        let mut breaker = CrashBreaker::default();
        for i in 0..5 {
            breaker.record(secs(i));
        }
        breaker.reset();
        assert_eq!(breaker.record(secs(6)), Verdict::Restart(secs(2)));
    }
}
