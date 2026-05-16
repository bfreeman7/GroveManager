import React from "react";
import { SiftCard } from "./SiftCard";
import { StationTimingTable } from "./StationTimingTable";
import { SyncStatusTable } from "./SyncStatusTable";
import type { OpenSprinklerLogResponse, OpenSprinklerSnapshotConfigured, StatusResponse } from "../types";

type Props = {
  status: StatusResponse | null;
  snapshot: OpenSprinklerSnapshotConfigured | null;
  runLog: OpenSprinklerLogResponse | null;
  osLoading: boolean;
  osNotConfigured: boolean;
  osError: string | null;
};

export function GroveOverview({
  status,
  snapshot,
  runLog,
  osLoading,
  osNotConfigured,
  osError,
}: Props) {
  return (
    <div className="overviewStrip overviewStrip--sticky card">
      <h2 className="sectionTitle">Overview</h2>

      <SiftCard assetName={status?.sift_asset} />

      <div className="overviewBlock">
        <h3 className="overviewBlockTitle">Sprinkler schedule</h3>
        <StationTimingTable
          snapshot={snapshot}
          runLog={runLog}
          loading={osLoading}
          notConfigured={osNotConfigured}
          error={osError}
        />
      </div>

      <div className="overviewBlock">
        <h3 className="overviewBlockTitle">Sensor sync to Sift</h3>
        <SyncStatusTable status={status} />
      </div>
    </div>
  );
}
