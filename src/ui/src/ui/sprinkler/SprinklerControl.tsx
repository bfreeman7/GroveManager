import React from "react";
import { StationGrid } from "./StationGrid";
import type { OpenSprinklerSnapshotConfigured } from "../types";

type Props = {
  snapshot: OpenSprinklerSnapshotConfigured;
  busySid: number | null;
  stationBusy: boolean;
  actionError: string | null;
  onStop: (sid: number) => void;
  onRun: (s: { id: number; name: string }) => void;
};

export function SprinklerControl({
  snapshot,
  busySid,
  stationBusy,
  actionError,
  onStop,
  onRun,
}: Props) {
  return (
    <>
      <div className="cardTitle" style={{ fontSize: 14, marginBottom: 8 }}>
        Stations
      </div>
      {actionError ? <div className="inlineErr">{actionError}</div> : null}
      <StationGrid
        stations={snapshot.summary.stations}
        busySid={busySid}
        stationBusy={stationBusy}
        onStop={onStop}
        onRun={onRun}
      />
    </>
  );
}
