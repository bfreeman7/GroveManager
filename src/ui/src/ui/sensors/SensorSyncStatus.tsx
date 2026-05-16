import React from "react";
import { formatTimeAndRelative } from "../shared/relativeTime";
import { lastSuccessfulForwardSync } from "../shared/syncEvents";
import type { StatusResponse } from "../types";

type Props = {
  status: StatusResponse | null;
};

export function SensorSyncStatus({ status }: Props) {
  const pending = status?.pending_forward ?? 0;
  const last = lastSuccessfulForwardSync(status?.recent_events);
  const now = new Date();
  const lastFmt = last ? formatTimeAndRelative(last.at, now) : null;

  return (
    <div className="syncStatusGrid">
      <div className="syncStatusItem">
        <div className="syncStatusValue">{pending}</div>
        <div className="syncStatusLabel">measurements waiting for Sift</div>
        <div className="syncStatusHint">
          Ecowitt readings are stored locally, then forwarded in batches by the edge service.
        </div>
      </div>
      <div className="syncStatusItem">
        <div className="syncStatusValue">
          {lastFmt ? lastFmt.time : "—"}
        </div>
        <div className="syncStatusLabel">
          last successful forward
          {lastFmt ? ` · ${lastFmt.relative}` : ""}
        </div>
        {last?.count != null ? (
          <div className="syncStatusHint">{last.count} measurements in that batch</div>
        ) : (
          <div className="syncStatusHint">Background loop runs every ~30s when configured</div>
        )}
      </div>
      <div className="syncStatusItem">
        <div className="syncStatusValue mono">{status?.total_measurements_indexed?.toLocaleString() ?? "—"}</div>
        <div className="syncStatusLabel">total indexed locally</div>
        <div className="syncStatusHint">
          Mode: <span className="mono">{status?.sift_mode ?? "—"}</span>
        </div>
      </div>
    </div>
  );
}
