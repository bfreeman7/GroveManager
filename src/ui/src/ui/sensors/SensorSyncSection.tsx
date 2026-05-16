import React from "react";
import { Section } from "../layout/Section";
import { Subsection } from "../layout/Subsection";
import { SensorSyncStatus } from "./SensorSyncStatus";
import { SensorSyncHistory } from "./SensorSyncHistory";
import type { StatusResponse, SystemEvent } from "../types";

type Props = {
  status: StatusResponse | null;
  events: SystemEvent[];
  onRefresh: () => void;
};

export function SensorSyncSection({ status, events, onRefresh }: Props) {
  return (
    <Section
      title="Moisture & temp (Sift)"
      description="Ecowitt ingest → edge queue → Sift"
      headerAction={
        <button className="btn secondary" type="button" onClick={onRefresh}>
          Refresh
        </button>
      }
    >
      <Subsection label="Status">
        <SensorSyncStatus status={status} />
      </Subsection>
      <Subsection
        label="History"
        hint="Forward batches only"
      >
        <SensorSyncHistory events={events} />
      </Subsection>
    </Section>
  );
}
