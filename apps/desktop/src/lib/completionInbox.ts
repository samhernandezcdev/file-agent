/** FA-017.1 §19a / FA-017.4 §2: a mutation completion the user has not yet
 * seen because they navigated away from its originating screen before it
 * arrived. Presentation-only: never persisted (gone on app restart), never
 * a substitute for History, never a retry mechanism.
 *
 * Generic over the outcome type (FA-017.4): the FIFO-cap/eviction
 * mechanics below are genuinely shared by any mutation kind that wants
 * this behavior (currently apply.items and destination_setup.prepare) --
 * but "ordinary vs unknown" is a PRODUCT classification specific to each
 * outcome's own shape, so it is never hardcoded here. SHARED FIFO
 * MECHANICS != SHARED PRODUCT SEMANTICS: this module knows nothing about
 * BatchApplyResultView, DestinationSetupResultView, or any other DTO --
 * callers supply an `isOrdinary` classifier (e.g.
 * `completionPresentation`/`destinationSetupCompletionPresentation`,
 * both in outcomeMessages.ts) instead. */
export type RetainedCompletion<TOutcome> = {
  id: string;
  managedRootId: string;
  outcome: TOutcome;
  receivedAt: number;
};

/** Only the "ordinary" subset is bounded -- UNKNOWN entries are never
 * counted here and never evicted, for every outcome kind that uses this
 * module. */
export const MAX_ORDINARY_NOTICES = 5;

/** Appends one completion. If it is ordinary (per the caller-supplied
 * classifier) and appending it would exceed MAX_ORDINARY_NOTICES, evicts
 * the single oldest ordinary entry first -- an entry the classifier
 * treats as non-ordinary (e.g. UNKNOWN) is never evicted by this, no
 * matter how many ordinary notices already exist. A later completion
 * never silently replaces an earlier unseen one; eviction only ever
 * removes the oldest ordinary entry, one at a time. */
export function appendCompletion<TOutcome>(
  list: readonly RetainedCompletion<TOutcome>[],
  entry: RetainedCompletion<TOutcome>,
  isOrdinary: (entry: RetainedCompletion<TOutcome>) => boolean,
): RetainedCompletion<TOutcome>[] {
  if (!isOrdinary(entry)) {
    return [...list, entry];
  }
  const ordinaryCount = list.filter(isOrdinary).length;
  if (ordinaryCount < MAX_ORDINARY_NOTICES) {
    return [...list, entry];
  }
  const oldestOrdinaryIndex = list.findIndex(isOrdinary);
  const next = list.slice();
  next.splice(oldestOrdinaryIndex, 1);
  next.push(entry);
  return next;
}

/** Removes exactly one entry, by id -- the only way any entry (ordinary or
 * not) is ever removed other than ordinary-cap eviction above. No backend
 * call, no retry, no mutation. Already fully generic; unchanged. */
export function removeCompletion<TOutcome>(
  list: readonly RetainedCompletion<TOutcome>[],
  id: string,
): RetainedCompletion<TOutcome>[] {
  return list.filter((entry) => entry.id !== id);
}
