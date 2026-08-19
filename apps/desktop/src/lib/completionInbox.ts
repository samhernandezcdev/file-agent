import type { BatchApplyResultView, ManagedRootUnavailableResultView } from "@file-agent/desktop-types";
import type { RustOutcome } from "../desktop";
import { completionPresentation } from "./outcomeMessages";

/** FA-017.1 §19a: an apply completion the user has not yet seen because
 * they navigated away from that root's Revisar screen before it arrived.
 * Presentation-only: never persisted (gone on app restart), never a
 * substitute for History, never a retry mechanism. */
export type RetainedCompletion = {
  id: string;
  managedRootId: string;
  outcome: RustOutcome<BatchApplyResultView | ManagedRootUnavailableResultView>;
  receivedAt: number;
};

/** Only the "ordinary" (RESULT ∪ KNOWN_NO_RESULT) subset is bounded --
 * UNKNOWN entries are never counted here and never evicted. */
export const MAX_ORDINARY_NOTICES = 5;

function isOrdinary(entry: RetainedCompletion): boolean {
  return completionPresentation(entry.outcome).kind !== "unknown";
}

/** Appends one completion. If it is ordinary and appending it would exceed
 * MAX_ORDINARY_NOTICES, evicts the single oldest ordinary entry first --
 * an UNKNOWN entry is never evicted by this, no matter how many ordinary
 * notices already exist. A later completion never silently replaces an
 * earlier unseen one; eviction only ever removes the oldest ordinary
 * entry, one at a time. */
export function appendCompletion(
  list: readonly RetainedCompletion[],
  entry: RetainedCompletion,
): RetainedCompletion[] {
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
 * UNKNOWN) is ever removed other than ordinary-cap eviction above. No
 * backend call, no retry, no mutation. */
export function removeCompletion(
  list: readonly RetainedCompletion[],
  id: string,
): RetainedCompletion[] {
  return list.filter((entry) => entry.id !== id);
}
