import React from "react";
import { TimingTable } from "../layout/TimingTable";
import { formatTimeAndRelative } from "../shared/relativeTime";
import { describeForwardHealth } from "../shared/forwardHealth";
import { lastForwardSync, lastSuccessfulForwardSync } from "../shared/syncEvents";
import type { StatusResponse } from "../types";

type Props = {
  status: StatusResponse | null;
};

export function SyncStatusTable({ status }: Props) {
  const pending = status?.pending_forward ?? 0;
  const forward = status?.forward;
  const health = describeForwardHealth(status);
  const lastAttempt = lastForwardSync(status?.recent_events);
  const lastSuccess = lastSuccessfulForwardSync(status?.recent_events);
  const last = lastSuccess ?? lastAttempt;
  const now = new Date();

  const statusCell = health
    ? {
        primary: health.title,
        secondary: health.failureLabel ?? health.detail,
        emphasis: health.tone !== "ok",
      }
    : {
        primary: "—",
        secondary: "Forward health not reported (redeploy edge API)",
      };

  let lastCell: { primary: string; time?: string; relative?: string; secondary?: string };
  if (forward?.last_success_at) {
    const at = new Date(forward.last_success_at);
    const { time, relative } = formatTimeAndRelative(at, now);
    lastCell = {
      primary: "Last successful sync",
      time,
      relative,
      secondary:
        forward.consecutive_failures > 0
          ? `${forward.consecutive_failures} failure(s) since`
          : lastSuccess?.count != null
            ? `${lastSuccess.count} measurements in last batch`
            : undefined,
    };
  } else if (last) {
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
    primary: pending === 0 ? "Caught up" : `${pending.toLocaleString()} behind`,
    secondary:
      pending === 0
        ? "Queue empty"
        : health?.oldestPendingLabel
          ? `Oldest ${health.oldestPendingLabel}`
          : `${status?.total_measurements_indexed?.toLocaleString() ?? "—"} total indexed`,
    emphasis: pending > 0 || Boolean(forward?.degraded),
  };

  const connectivityCell = {
    primary: health?.connectivityLabel ?? "—",
    secondary: health?.connectivityHint ?? `Mode: ${status?.sift_mode ?? "—"}`,
    emphasis: health?.connectivityLabel === "Offline",
  };

  return (
    <TimingTable
      columns={[
        { key: "status", header: "Status" },
        { key: "last", header: "Last success" },
        { key: "backlog", header: "Backlog" },
        { key: "net", header: "Network" },
      ]}
      rows={[
        {
          key: "sync",
          label: "Sift",
          cells: {
            status: statusCell,
            last: lastCell,
            backlog: backlogCell,
            net: connectivityCell,
          },
        },
      ]}
    />
  );
}
