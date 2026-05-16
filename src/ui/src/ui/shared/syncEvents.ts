import type { SystemEvent } from "../types";

export type LastForwardSync = {
  at: Date;
  count: number | null;
  failed: boolean;
};

export function lastForwardSync(events: SystemEvent[] | undefined): LastForwardSync | null {
  if (!events?.length) return null;
  for (const e of events) {
    if (e.component !== "forwarder") continue;
    const at = new Date(e.ts);
    if (Number.isNaN(at.getTime())) continue;
    if (e.message === "forwarded_batch" && e.level === "info") {
      const details = e.details as { count?: number } | null;
      return { at, count: details?.count ?? null, failed: false };
    }
    if (e.message === "forward_failed") {
      return { at, count: null, failed: true };
    }
  }
  return null;
}

/** Most recent successful batch only (for “last sync” displays). */
export function lastSuccessfulForwardSync(events: SystemEvent[] | undefined): LastForwardSync | null {
  if (!events?.length) return null;
  for (const e of events) {
    if (e.component !== "forwarder") continue;
    if (e.message !== "forwarded_batch" || e.level !== "info") continue;
    const at = new Date(e.ts);
    if (Number.isNaN(at.getTime())) continue;
    const details = e.details as { count?: number } | null;
    return { at, count: details?.count ?? null, failed: false };
  }
  return null;
}

export function summarizeForwardEvent(e: SystemEvent): string {
  if (e.message === "forwarded_batch") {
    const d = e.details as { count?: number; ingest_timestamps?: number } | null;
    const n = d?.count;
    const ts = d?.ingest_timestamps;
    if (n != null && ts != null) return `Sent ${n} rows (${ts} timestamps)`;
    if (n != null) return `Sent ${n} rows`;
    return "Batch sent";
  }
  if (e.message === "forward_failed") return "Forward failed";
  if (e.message === "mark_forwarded_failed_after_send") return "DB update failed after send";
  return e.message;
}
