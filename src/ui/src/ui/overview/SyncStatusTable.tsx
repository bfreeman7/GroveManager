import React from "react";
import { TimingTable } from "../layout/TimingTable";
import { formatTimeAndRelative } from "../shared/relativeTime";
import { lastForwardSync, lastSuccessfulForwardSync } from "../shared/syncEvents";
import type { StatusResponse } from "../types";

type Props = {
  status: StatusResponse | null;
};

export function SyncStatusTable({ status }: Props) {
  const pending = status?.pending_forward ?? 0;
  const lastAttempt = lastForwardSync(status?.recent_events);
  const lastSuccess = lastSuccessfulForwardSync(status?.recent_events);
  const last = lastSuccess ?? lastAttempt;
  const now = new Date();

  let lastCell: { primary: string; time?: string; relative?: string; secondary?: string };
  if (last) {
    const { time, relative } = formatTimeAndRelative(last.at, now);
    lastCell = {
      primary: last.failed ? "Last attempt failed" : "Last successful sync",
      time,
      relative,
      secondary:
        last.count != null && !last.failed ? `${last.count} measurements sent` : undefined,
    };
  } else {
    lastCell = { primary: "—", secondary: "No sync events logged yet" };
  }

  const backlogCell = {
    primary: pending === 0 ? "Caught up" : `${pending} behind`,
    secondary:
      pending === 0
        ? "Queue empty"
        : `${status?.total_measurements_indexed?.toLocaleString() ?? "—"} total indexed`,
    emphasis: pending > 0,
  };

  const modeCell = {
    primary: status?.sift_mode ?? "—",
    secondary: "Forwarding mode",
  };

  return (
    <TimingTable
      columns={[
        { key: "last", header: "Last sync" },
        { key: "backlog", header: "Backlog" },
        { key: "mode", header: "Mode" },
      ]}
      rows={[
        {
          key: "sync",
          label: "Sift",
          cells: { last: lastCell, backlog: backlogCell, mode: modeCell },
        },
      ]}
    />
  );
}
