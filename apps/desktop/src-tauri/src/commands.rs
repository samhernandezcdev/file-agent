//! FA-017 Round 7's closed, exhaustive 14-command catalogue. This is the
//! ONE place a command name string is ever trusted to mean something --
//! `parse()` fails closed (returns `None`) for anything else, and
//! `retry_safety()` has no wildcard/default arm, so adding a 15th command
//! without updating both functions is a compile error, not a silent gap.
//!
//! This enum, its `parse`/`retry_safety`/`name` mappings, and
//! `src/file_agent/desktop_api/commands.json` are three independent
//! encodings of the exact same 14-entry contract; see
//! `tests/manifest_drift_guard.rs` for the test proving all three agree.
//! The manifest is metadata/a drift guard -- it is never consulted at
//! runtime and never grants execution authority.

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum DesktopCommand {
    ManagedRootsAdd,
    ManagedRootsRemove,
    ManagedRootsList,
    AnalysisRun,
    AnalysisReanalyzeFile,
    PlanCreate,
    ReviewApprove,
    ReviewSkip,
    ApplyItem,
    ApplyItems,
    HistoryGetBatch,
    HistoryListRecent,
    RecoveryUndoTransaction,
    RecoveryRestoreCapture,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RetrySafety {
    SafeRetry,
    UnknownOnDisconnect,
}

pub const ALL_COMMANDS: [DesktopCommand; 14] = [
    DesktopCommand::ManagedRootsAdd,
    DesktopCommand::ManagedRootsRemove,
    DesktopCommand::ManagedRootsList,
    DesktopCommand::AnalysisRun,
    DesktopCommand::AnalysisReanalyzeFile,
    DesktopCommand::PlanCreate,
    DesktopCommand::ReviewApprove,
    DesktopCommand::ReviewSkip,
    DesktopCommand::ApplyItem,
    DesktopCommand::ApplyItems,
    DesktopCommand::HistoryGetBatch,
    DesktopCommand::HistoryListRecent,
    DesktopCommand::RecoveryUndoTransaction,
    DesktopCommand::RecoveryRestoreCapture,
];

impl DesktopCommand {
    /// Fails closed: any string not exactly one of the 14 known command
    /// names returns `None` -- the caller must reject the request before
    /// it ever reaches the sidecar. No generic-invoke, no dynamic
    /// dispatch.
    pub fn parse(name: &str) -> Option<DesktopCommand> {
        match name {
            "managed_roots.add" => Some(DesktopCommand::ManagedRootsAdd),
            "managed_roots.remove" => Some(DesktopCommand::ManagedRootsRemove),
            "managed_roots.list" => Some(DesktopCommand::ManagedRootsList),
            "analysis.run" => Some(DesktopCommand::AnalysisRun),
            "analysis.reanalyze_file" => Some(DesktopCommand::AnalysisReanalyzeFile),
            "plan.create" => Some(DesktopCommand::PlanCreate),
            "review.approve" => Some(DesktopCommand::ReviewApprove),
            "review.skip" => Some(DesktopCommand::ReviewSkip),
            "apply.item" => Some(DesktopCommand::ApplyItem),
            "apply.items" => Some(DesktopCommand::ApplyItems),
            "history.get_batch" => Some(DesktopCommand::HistoryGetBatch),
            "history.list_recent" => Some(DesktopCommand::HistoryListRecent),
            "recovery.undo_transaction" => Some(DesktopCommand::RecoveryUndoTransaction),
            "recovery.restore_capture" => Some(DesktopCommand::RecoveryRestoreCapture),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            DesktopCommand::ManagedRootsAdd => "managed_roots.add",
            DesktopCommand::ManagedRootsRemove => "managed_roots.remove",
            DesktopCommand::ManagedRootsList => "managed_roots.list",
            DesktopCommand::AnalysisRun => "analysis.run",
            DesktopCommand::AnalysisReanalyzeFile => "analysis.reanalyze_file",
            DesktopCommand::PlanCreate => "plan.create",
            DesktopCommand::ReviewApprove => "review.approve",
            DesktopCommand::ReviewSkip => "review.skip",
            DesktopCommand::ApplyItem => "apply.item",
            DesktopCommand::ApplyItems => "apply.items",
            DesktopCommand::HistoryGetBatch => "history.get_batch",
            DesktopCommand::HistoryListRecent => "history.list_recent",
            DesktopCommand::RecoveryUndoTransaction => "recovery.undo_transaction",
            DesktopCommand::RecoveryRestoreCapture => "recovery.restore_capture",
        }
    }

    /// Retry-safety classification -- NOT "read-only vs mutating". See
    /// FA-017 Round 2/3: `analysis.run` is SAFE_RETRY despite writing
    /// audit state (rerunning analysis creates a fresh valid analysis
    /// generation); `review.approve`/`review.skip` are
    /// UNKNOWN_ON_DISCONNECT despite never moving a managed file (they
    /// durably persist a human decision). No wildcard/default arm --
    /// every variant is listed explicitly so a new command can never
    /// silently inherit an unintended classification.
    pub fn retry_safety(self) -> RetrySafety {
        match self {
            DesktopCommand::ManagedRootsList => RetrySafety::SafeRetry,
            DesktopCommand::AnalysisRun => RetrySafety::SafeRetry,
            DesktopCommand::AnalysisReanalyzeFile => RetrySafety::SafeRetry,
            DesktopCommand::PlanCreate => RetrySafety::SafeRetry,
            DesktopCommand::HistoryGetBatch => RetrySafety::SafeRetry,
            DesktopCommand::HistoryListRecent => RetrySafety::SafeRetry,
            DesktopCommand::ManagedRootsAdd => RetrySafety::UnknownOnDisconnect,
            DesktopCommand::ManagedRootsRemove => RetrySafety::UnknownOnDisconnect,
            DesktopCommand::ReviewApprove => RetrySafety::UnknownOnDisconnect,
            DesktopCommand::ReviewSkip => RetrySafety::UnknownOnDisconnect,
            DesktopCommand::ApplyItem => RetrySafety::UnknownOnDisconnect,
            DesktopCommand::ApplyItems => RetrySafety::UnknownOnDisconnect,
            DesktopCommand::RecoveryUndoTransaction => RetrySafety::UnknownOnDisconnect,
            DesktopCommand::RecoveryRestoreCapture => RetrySafety::UnknownOnDisconnect,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn manual_count_all_commands_is_fourteen() {
        assert_eq!(ALL_COMMANDS.len(), 14);
    }

    #[test]
    fn parse_round_trips_every_known_name() {
        for command in ALL_COMMANDS {
            assert_eq!(DesktopCommand::parse(command.name()), Some(command));
        }
    }

    #[test]
    fn parse_rejects_unknown_command_fails_closed() {
        assert_eq!(DesktopCommand::parse("file_agent.run_arbitrary_code"), None);
        assert_eq!(DesktopCommand::parse(""), None);
        assert_eq!(DesktopCommand::parse("managed_roots.ADD"), None);
    }

    #[test]
    fn retry_safety_split_is_exactly_six_and_eight() {
        let safe_retry_count = ALL_COMMANDS
            .iter()
            .filter(|c| c.retry_safety() == RetrySafety::SafeRetry)
            .count();
        let unknown_count = ALL_COMMANDS
            .iter()
            .filter(|c| c.retry_safety() == RetrySafety::UnknownOnDisconnect)
            .count();
        assert_eq!(safe_retry_count, 6);
        assert_eq!(unknown_count, 8);
    }
}
