import React from "react";
import { TimingTable } from "../layout/TimingTable";
import { buildStationTimingRows } from "../shared/opensprinklerTiming";
import type { OpenSprinklerLogResponse, OpenSprinklerSnapshotConfigured } from "../types";

const COLUMNS = [
  { key: "last", header: "Last" },
  { key: "current", header: "Current" },
  { key: "next", header: "Next" },
] as const;

type Props = {
  snapshot: OpenSprinklerSnapshotConfigured | null;
  runLog: OpenSprinklerLogResponse | null;
  loading: boolean;
  notConfigured: boolean;
  error: string | null;
};

export function StationTimingTable({ snapshot, runLog, loading, notConfigured, error }: Props) {
  if (error) {
    return <div className="muted">Sprinkler timing unavailable.</div>;
  }
  if (loading && !snapshot) {
    return <div className="muted">Loading sprinkler status…</div>;
  }
  if (notConfigured || !snapshot) {
    return <div className="muted">Open Sprinkler not configured.</div>;
  }

  const rows = buildStationTimingRows(snapshot, runLog).map((r) => ({
    key: String(r.id),
    label: r.name,
    cells: { last: r.last, current: r.current, next: r.next },
  }));

  return (
    <TimingTable
      columns={[...COLUMNS]}
      rows={rows}
      emptyMessage="No stations configured."
    />
  );
}
