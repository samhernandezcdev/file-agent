/**
 * GENERATED FILE -- DO NOT EDIT BY HAND.
 *
 * Produced from src/file_agent/desktop_api's Pydantic View DTOs and
 * request-param models via:
 *   uv run python scripts/generate_desktop_view_schema.py
 *   pnpm --filter @file-agent/desktop-types generate
 *
 * These types are a COMPILE-TIME contract only. Nothing in this file
 * performs runtime validation of data arriving from the sidecar -- see
 * the FA-017 design plan's "TYPE GENERATION" section for why v1
 * deliberately does not add a runtime validator (Zod/Ajv) on top of this.
 */

export type Fileid = string;
export type Detail = string;
export type Severity = string;
export type Suggestedaction = string;
export type Title = string;
export type Sourcedisplaypath = string | null;
export type Fileid1 = string;
export type Failures = AnalysisFailureView[];
export type Filesdiscovered = number;
export type Categorylabel = string;
export type Confidence = number;
export type Fileid2 = string;
export type Filename = string;
export type Policydecisionid = string;
export type Proposeddestinationcategorylabel = string | null;
export type Requiresreview = boolean;
export type Sourcedisplaypath1 = string;
export type Items = AnalyzedItemView[];
export type Outcome = "ok";
export type Scanid = string;
export type Managedrootid = string;
export type Policydecisionid1 = string;
export type Policydecisionids = string[];
export type Destinationdisplaypath = string | null;
export type Policydecisionid2 = string;
export type Status = "succeeded" | "rejected" | "failed";
export type Transactionid = string | null;
export type Destinationdisplaypath1 = string | null;
export type Filename1 = string | null;
export type Inputindex = number;
export type Policydecisionid3 = string;
export type Status1 = string;
export type Transactionid1 = string | null;
export type Batchid = string;
export type Completedat = string | null;
export type Items1 = BatchApplyItemResultView[];
export type Managedrootid1 = string | null;
export type Outcome1 = "ok";
export type Startedat = string;
export type Status2 = "completed" | "incomplete";
export type Applied = number;
export type Invalid = number;
export type Notapplied = number;
export type Processed = number;
export type Selected = number;
export type Skipped = number;
export type Appliedcount = number;
export type Batchid1 = string;
export type Completedat1 = string | null;
export type Invalidcount = number;
export type Items2 = BatchHistoryItemView[] | null;
export type Inputindex1 = number;
export type Policydecisionid4 = string;
export type Reasondetail = string | null;
export type Status3 = string;
export type Transactionid2 = string | null;
export type Managedrootid2 = string | null;
export type Notappliedcount = number;
export type Outcome2 = "found";
export type Processedcount = number;
export type Rowtype = "entry";
export type Selectedcount = number;
export type Skippedcount = number;
export type Startedat1 = string;
export type Status4 = "completed" | "incomplete";
/**
 * A logical organization destination — not a filesystem path, absolute
 * or relative. Resolving this into an actual location (organization root,
 * category folder, filename) is explicitly deferred to a future ticket;
 * this enum exists only to constrain proposals to a small, stable, typed
 * vocabulary instead of letting arbitrary strings ("Docs", "documents/",
 * ad-hoc casing) enter durable proposal records.
 */
export type DestinationCategory = "documents" | "images" | "audio" | "video" | "archives" | "code" | "executables";
export type Destinationlabel = string;
export type Status5 = "prepared" | "already_available" | "not_prepared";
export type Destinationcategories = DestinationCategory[];
export type Managedrootid3 = string;
export type Items3 = DestinationSetupItemResultView[];
export type Managedrootid4 = string;
export type Outcome3 = "ok";
export type Setupid = string;
export type Batchid2 = string;
export type Includeitems = boolean;
export type Limit = number;
export type Outcome4 = "unavailable";
export type Displaypath = string;
export type Id = string;
export type Status6 = "available" | "unavailable";
export type Roots = ManagedRootView[];
export type Outcome5 = "managed_root_unavailable";
export type Path = string;
export type Managedrootid5 = string;
export type Affectedfilenames = string[];
export type Categorylabel1 = string;
export type Destinationlabel1 = string;
export type Variant = "missing_destination_folder";
export type Policydecisionids1 = string[];
export type Actionid = string;
export type Categorylabel2 = string;
export type Destinationdisplaypath2 = string | null;
export type Detail1 = string;
export type Filename2 = string;
export type Selectable = boolean;
export type Severity1 = string;
export type Sourcedisplaypath2 = string;
export type Status7 = string;
export type Title1 = string;
export type Blocked = number;
export type Conflicts = number;
export type Filestotal = number;
export type Invalid1 = number;
export type Issues = number;
export type Noaction = number;
export type Protected = number;
export type Ready = number;
export type Reviewrequired = number;
export type Skipped1 = number;
export type Attentions = PlanAttentionView[];
export type Id1 = string;
export type Items4 = PlanItemView[];
export type Managedrootid6 = string | null;
export type Outcome6 = "ok";
export type Rootdisplaypath = string | null;
export type Structuralprotectionnote = string | null;
export type Batchid3 = string;
export type Rowtype1 = "unavailable";
export type Startedat2 = string | null;
export type Rows = (BatchHistoryEntryView | UnavailableBatchHistoryRowView)[];
export type Captureid = string;
export type Transactionid3 = string;
export type Managedrootid7 = string;
export type Status8 = "succeeded" | "rejected";
export type Captureid1 = string;
export type Recoveryid = string | null;
export type Restoreddisplaypath = string | null;
export type Status9 = "succeeded" | "rejected" | "failed";
export type Note = string | null;
export type Policydecisionid5 = string;
export type Policydecisionid6 = string;
export type Status10 = "succeeded" | "rejected";
export type Recoveryid1 = string | null;
export type Restoreddisplaypath1 = string | null;
export type Status11 = "succeeded" | "rejected" | "failed";
export type Transactionid4 = string;

export interface DesktopApiTypesRoot {
  AnalysisFailureView: AnalysisFailureView;
  AnalysisReanalyzeFileParams: AnalysisReanalyzeFileParams;
  AnalysisResultView: AnalysisResultView;
  AnalysisRunParams: AnalysisRunParams;
  AnalyzedItemView: AnalyzedItemView;
  ApplyItemParams: ApplyItemParams;
  ApplyItemsParams: ApplyItemsParams;
  ApplyResultView: ApplyResultView;
  BatchApplyItemResultView: BatchApplyItemResultView;
  BatchApplyResultView: BatchApplyResultView;
  BatchApplySummaryView: BatchApplySummaryView;
  BatchHistoryEntryView: BatchHistoryEntryView;
  BatchHistoryItemView: BatchHistoryItemView;
  DestinationCategory: DestinationCategory;
  DestinationSetupItemResultView: DestinationSetupItemResultView;
  DestinationSetupPrepareParams: DestinationSetupPrepareParams;
  DestinationSetupResultView: DestinationSetupResultView;
  HistoryGetBatchParams: HistoryGetBatchParams;
  HistoryListRecentParams: HistoryListRecentParams;
  HistoryLookupFailureView: HistoryLookupFailureView;
  ManagedRootListView: ManagedRootListView;
  ManagedRootUnavailableResultView: ManagedRootUnavailableResultView;
  ManagedRootView: ManagedRootView;
  ManagedRootsAddParams: ManagedRootsAddParams;
  ManagedRootsListParams: ManagedRootsListParams;
  ManagedRootsRemoveParams: ManagedRootsRemoveParams;
  PlanAttentionView: PlanAttentionView;
  PlanCreateParams: PlanCreateParams;
  PlanItemView: PlanItemView;
  PlanSummaryView: PlanSummaryView;
  PlanView: PlanView;
  RecentHistoryView: RecentHistoryView;
  RecoveryRestoreCaptureParams: RecoveryRestoreCaptureParams;
  RecoveryUndoTransactionParams: RecoveryUndoTransactionParams;
  RemoveManagedRootResultView: RemoveManagedRootResultView;
  RestoreResultView: RestoreResultView;
  ReviewActionParams: ReviewActionParams;
  ReviewActionResultView: ReviewActionResultView;
  UnavailableBatchHistoryRowView: UnavailableBatchHistoryRowView;
  UndoResultView: UndoResultView;
  UserMessageView: UserMessageView;
}
export interface AnalysisFailureView {
  fileId: Fileid;
  message: UserMessageView;
  sourceDisplayPath: Sourcedisplaypath;
}
export interface UserMessageView {
  detail: Detail;
  severity: Severity;
  suggestedAction: Suggestedaction;
  title: Title;
}
export interface AnalysisReanalyzeFileParams {
  fileId: Fileid1;
}
export interface AnalysisResultView {
  failures: Failures;
  filesDiscovered: Filesdiscovered;
  items: Items;
  outcome: Outcome;
  protectedTreesMessage: UserMessageView | null;
  scanId: Scanid;
}
export interface AnalyzedItemView {
  categoryLabel: Categorylabel;
  confidence: Confidence;
  fileId: Fileid2;
  filename: Filename;
  policyDecisionId: Policydecisionid;
  proposedDestinationCategoryLabel: Proposeddestinationcategorylabel;
  requiresReview: Requiresreview;
  sourceDisplayPath: Sourcedisplaypath1;
}
export interface AnalysisRunParams {
  managedRootId: Managedrootid;
}
export interface ApplyItemParams {
  policyDecisionId: Policydecisionid1;
}
export interface ApplyItemsParams {
  policyDecisionIds: Policydecisionids;
}
export interface ApplyResultView {
  destinationDisplayPath: Destinationdisplaypath;
  message: UserMessageView | null;
  policyDecisionId: Policydecisionid2;
  status: Status;
  transactionId: Transactionid;
}
export interface BatchApplyItemResultView {
  destinationDisplayPath: Destinationdisplaypath1;
  filename: Filename1;
  inputIndex: Inputindex;
  message: UserMessageView;
  policyDecisionId: Policydecisionid3;
  status: Status1;
  transactionId: Transactionid1;
}
export interface BatchApplyResultView {
  batchId: Batchid;
  completedAt: Completedat;
  items: Items1;
  managedRootId: Managedrootid1;
  outcome: Outcome1;
  startedAt: Startedat;
  status: Status2;
  summary: BatchApplySummaryView;
  summaryMessage: UserMessageView;
}
export interface BatchApplySummaryView {
  applied: Applied;
  invalid: Invalid;
  notApplied: Notapplied;
  processed: Processed;
  selected: Selected;
  skipped: Skipped;
}
export interface BatchHistoryEntryView {
  appliedCount: Appliedcount;
  batchId: Batchid1;
  completedAt: Completedat1;
  invalidCount: Invalidcount;
  items: Items2;
  managedRootId: Managedrootid2;
  notAppliedCount: Notappliedcount;
  outcome: Outcome2;
  processedCount: Processedcount;
  rowType: Rowtype;
  selectedCount: Selectedcount;
  skippedCount: Skippedcount;
  startedAt: Startedat1;
  status: Status4;
  summaryMessage: UserMessageView;
}
export interface BatchHistoryItemView {
  inputIndex: Inputindex1;
  policyDecisionId: Policydecisionid4;
  reasonDetail: Reasondetail;
  status: Status3;
  transactionId: Transactionid2;
}
export interface DestinationSetupItemResultView {
  destinationCategory: DestinationCategory;
  destinationLabel: Destinationlabel;
  message: UserMessageView;
  status: Status5;
}
export interface DestinationSetupPrepareParams {
  destinationCategories: Destinationcategories;
  managedRootId: Managedrootid3;
}
export interface DestinationSetupResultView {
  items: Items3;
  managedRootId: Managedrootid4;
  outcome: Outcome3;
  setupId: Setupid;
  summaryMessage: UserMessageView;
}
export interface HistoryGetBatchParams {
  batchId: Batchid2;
  includeItems?: Includeitems;
}
export interface HistoryListRecentParams {
  limit?: Limit;
}
export interface HistoryLookupFailureView {
  message: UserMessageView;
  outcome: Outcome4;
}
export interface ManagedRootListView {
  roots: Roots;
}
export interface ManagedRootView {
  displayPath: Displaypath;
  id: Id;
  status: Status6;
}
/**
 * The `outcome` discriminant shared by every command whose
 * FileAgentApplicationService method can return ManagedRootUnavailable
 * instead of its normal result -- analysis.run, plan.create, apply.items.
 * Not an exception/transport error: a legitimate, expected business
 * outcome, delivered as a normal `ok: true` terminal frame like any
 * other result.
 */
export interface ManagedRootUnavailableResultView {
  message: UserMessageView;
  outcome: Outcome5;
}
export interface ManagedRootsAddParams {
  path: Path;
}
export interface ManagedRootsListParams {}
export interface ManagedRootsRemoveParams {
  managedRootId: Managedrootid5;
}
/**
 * FA-017.1 §18: an additive, presentation-owned aggregation over items
 * that share the same underlying blocker -- computed here so React never
 * branches on `reason_code` itself (which never appears on this DTO, or
 * anywhere else on the wire).
 */
export interface PlanAttentionView {
  affectedFilenames: Affectedfilenames;
  categoryLabel: Categorylabel1;
  destinationCategory: DestinationCategory;
  destinationLabel: Destinationlabel1;
  message: UserMessageView;
  variant: Variant;
}
export interface PlanCreateParams {
  policyDecisionIds: Policydecisionids1;
}
export interface PlanItemView {
  actionId: Actionid;
  categoryLabel: Categorylabel2;
  destinationDisplayPath: Destinationdisplaypath2;
  detail: Detail1;
  filename: Filename2;
  selectable: Selectable;
  severity: Severity1;
  sourceDisplayPath: Sourcedisplaypath2;
  status: Status7;
  title: Title1;
}
export interface PlanSummaryView {
  blocked: Blocked;
  conflicts: Conflicts;
  filesTotal: Filestotal;
  invalid: Invalid1;
  issues: Issues;
  noAction: Noaction;
  protected: Protected;
  ready: Ready;
  reviewRequired: Reviewrequired;
  skipped: Skipped1;
}
export interface PlanView {
  attentions: Attentions;
  id: Id1;
  items: Items4;
  managedRootId: Managedrootid6;
  outcome: Outcome6;
  rootDisplayPath: Rootdisplaypath;
  structuralProtectionNote: Structuralprotectionnote;
  summary: PlanSummaryView;
}
export interface RecentHistoryView {
  rows: Rows;
}
export interface UnavailableBatchHistoryRowView {
  batchId: Batchid3;
  message: UserMessageView;
  rowType: Rowtype1;
  startedAt: Startedat2;
}
export interface RecoveryRestoreCaptureParams {
  captureId: Captureid;
}
export interface RecoveryUndoTransactionParams {
  transactionId: Transactionid3;
}
export interface RemoveManagedRootResultView {
  managedRootId: Managedrootid7;
  message: UserMessageView | null;
  status: Status8;
}
export interface RestoreResultView {
  captureId: Captureid1;
  message: UserMessageView | null;
  recoveryId: Recoveryid;
  restoredDisplayPath: Restoreddisplaypath;
  status: Status9;
}
export interface ReviewActionParams {
  note?: Note;
  policyDecisionId: Policydecisionid5;
}
export interface ReviewActionResultView {
  message: UserMessageView | null;
  policyDecisionId: Policydecisionid6;
  status: Status10;
}
export interface UndoResultView {
  message: UserMessageView | null;
  recoveryId: Recoveryid1;
  restoredDisplayPath: Restoreddisplaypath1;
  status: Status11;
  transactionId: Transactionid4;
}
