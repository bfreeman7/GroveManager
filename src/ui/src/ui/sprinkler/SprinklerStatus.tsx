import React from "react";
import { formatDeviceTime } from "../shared/format";
import { ProgramList } from "./ProgramList";
import type { OpenSprinklerSnapshotConfigured } from "../types";

type Props = {
  snapshot: OpenSprinklerSnapshotConfigured;
};

export function SprinklerStatus({ snapshot }: Props) {
  const { summary, fetched_at } = snapshot;
  const ctrl = summary.controller;

  return (
    <>
      <div className="muted" style={{ marginBottom: 8 }}>
        Updated {fetched_at ? new Date(fetched_at).toLocaleString() : "—"}
      </div>
      <div className="kv" style={{ marginBottom: 14 }}>
        <div className="k">rain delay (days)</div>
        <div className="v mono">{ctrl.rd ?? "—"}</div>
        <div className="k">device time</div>
        <div className="v mono">{formatDeviceTime(ctrl.devt)}</div>
      </div>
      <div className="cardTitle" style={{ fontSize: 14, marginBottom: 8 }}>
        Programs
      </div>
      <ProgramList programs={summary.programs} />
    </>
  );
}
