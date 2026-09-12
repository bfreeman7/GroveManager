import React from "react";
import { describeForwardHealth } from "../shared/forwardHealth";
import { lastSuccessfulForwardSync } from "../shared/syncEvents";
import { formatTimeAndRelative } from "../shared/relativeTime";
import type { StatusResponse } from "../types";

type Props = {
  status: StatusResponse | null;
};

export function SensorSyncStatus({ status }: Props) {
  const pending = status?.pending_forward ?? 0;
  const forward = status?.forward;
  const health = describeForwardHealth(status);
  const last = lastSuccessfulForwardSync(status?.recent_events);
  const now = new Date();
  const successAt = forward?.last_success_at
    ? new Date(forward.last_success_at)
    : last?.at ?? null;
  const lastFmt = successAt ? formatTimeAndRelative(successAt, now) : null;

  const statusToneClass =
    health?.tone === "error"
      ? "syncStatusItem--error"
      : health?.tone === "warning"
        ? "syncStatusItem--warning"
        : "";

  return (
    <div className="syncStatusGrid syncStatusGrid--4">
      <div className={`syncStatusItem ${statusToneClass}`}>
        <div className="syncStatusValue syncStatusValue--text">
          {health ? (
            <>
              <span className={`pill ${health.tone === "error" ? "error" : health.tone === "warning" ? "warning" : "success"}`}>
                {health.pillLabel}
              </span>{" "}
              {health.title}
            </>
          ) : (
            "—"
          )}
        </div>
        <div className="syncStatusLabel">forward health</div>
        <div className="syncStatusHint">
          {health?.failureLabel ?? health?.detail ?? "Waiting for edge status…"}
        </div>
      </div>

      <div className={`syncStatusItem ${pending > 0 ? "syncStatusItem--emphasis" : ""}`}>
        <div className="syncStatusValue">{pending.toLocaleString()}</div>
        <div className="syncStatusLabel">measurements waiting for Sift</div>
        <div className="syncStatusHint">
          {health?.oldestPendingLabel
            ? `Oldest pending ${health.oldestPendingLabel}`
            : "Ecowitt readings are stored locally, then forwarded in batches."}
        </div>
      </div>

      <div className="syncStatusItem">
        <div className="syncStatusValue">{lastFmt ? lastFmt.time : "—"}</div>
        <div className="syncStatusLabel">
          last successful forward
          {lastFmt ? ` · ${lastFmt.relative}` : ""}
        </div>
        <div className="syncStatusHint">
          {forward?.consecutive_failures
            ? `${forward.consecutive_failures} consecutive failure(s)${
                forward.failure_streak_seconds
                  ? ` · streak ${Math.round(forward.failure_streak_seconds / 60)}m`
                  : ""
              }`
            : last?.count != null
              ? `${last.count} measurements in that batch`
              : "Background loop runs every ~30s when configured"}
        </div>
      </div>

      <div
        className={`syncStatusItem ${
          health?.connectivityLabel === "Offline" ? "syncStatusItem--warning" : ""
        }`}
      >
        <div className="syncStatusValue syncStatusValue--text">
          {health?.connectivityLabel ?? "—"}
        </div>
        <div className="syncStatusLabel">Sift network</div>
        <div className="syncStatusHint">
          {health?.connectivityHint ?? `Mode: ${status?.sift_mode ?? "—"}`}
          {status?.sift_mode ? ` · mode ${status.sift_mode}` : ""}
        </div>
      </div>
    </div>
  );
}
