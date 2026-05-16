import React from "react";
import { PageShell } from "./layout/PageShell";
import { PageHeader } from "./layout/PageHeader";
import { GroveOverview } from "./overview/GroveOverview";
import { SensorSyncSection } from "./sensors/SensorSyncSection";
import { SprinklerSection } from "./sprinkler/SprinklerSection";
import { DeviceConfigSection } from "./config/DeviceConfigSection";
import { DiagnosticsSection } from "./config/DiagnosticsSection";
import { ApiErrorBanner } from "./shared/ApiErrorBanner";
import { useEdgeStatus } from "./hooks/useEdgeStatus";
import { useOpenSprinkler } from "./sprinkler/hooks/useOpenSprinkler";

export function App() {
  const edge = useEdgeStatus();
  const os = useOpenSprinkler();

  const opensprinklerConfigured = !os.notConfigured && !os.error && Boolean(os.snapshot);

  return (
    <PageShell>
      <PageHeader title="Grove UI" subtitle="Orchard edge monitor" />

      <div className="pageStack">
        {edge.error ? <ApiErrorBanner message={edge.error} /> : null}

        <GroveOverview
          status={edge.status}
          snapshot={os.snapshot}
          runLog={os.runLog}
          osLoading={os.loading}
          osNotConfigured={os.notConfigured}
          osError={os.error}
        />

        <SprinklerSection os={os} />

        <SensorSyncSection
          status={edge.status}
          events={edge.status?.recent_events ?? []}
          onRefresh={() => void edge.reload()}
        />

        <DeviceConfigSection status={edge.status} opensprinklerConfigured={opensprinklerConfigured} />

        <DiagnosticsSection
          forwardResult={edge.forwardResult}
          forwardError={edge.forwardError}
          allEvents={edge.status?.recent_events ?? []}
        />
      </div>
    </PageShell>
  );
}
