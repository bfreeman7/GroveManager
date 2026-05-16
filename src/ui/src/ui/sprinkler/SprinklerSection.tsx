import React from "react";
import { Section } from "../layout/Section";
import { Subsection } from "../layout/Subsection";
import { formatJson } from "../shared/format";
import type { useOpenSprinkler } from "./hooks/useOpenSprinkler";
import { SprinklerStatus } from "./SprinklerStatus";
import { SprinklerControl } from "./SprinklerControl";
import { SprinklerHistory } from "./SprinklerHistory";
import { RunStationModal } from "./RunStationModal";

type OpenSprinklerState = ReturnType<typeof useOpenSprinkler>;

type Props = {
  os: OpenSprinklerState;
};

export function SprinklerSection({ os }: Props) {
  if (os.error) {
    return (
      <Section id="sprinkler" title="Sprinkler" className="error">
        <pre className="pre">{os.error}</pre>
        <button className="btn secondary" type="button" onClick={() => void os.reload()}>
          Retry
        </button>
      </Section>
    );
  }

  if (os.loading && !os.notConfigured && !os.snapshot) {
    return (
      <Section id="sprinkler" title="Sprinkler">
        <div className="muted">Loading…</div>
      </Section>
    );
  }

  if (os.notConfigured) {
    return (
      <Section id="sprinkler" title="Sprinkler">
        <div className="muted">Not configured on the edge service.</div>
        <div className="hint" style={{ marginTop: 10 }}>
          Set <code>OPENSPRINKLER_URL</code> and <code>OPENSPRINKLER_PASSWORD</code> or{" "}
          <code>OPENSPRINKLER_PW_MD5</code> in <code>orchardmonitor.env</code>, then restart the
          service.
        </div>
      </Section>
    );
  }

  if (!os.snapshot) {
    return null;
  }

  return (
    <Section id="sprinkler" title="Sprinkler">
      <div className="cardTitleRow">
        <span className="muted">Open Sprinkler</span>
        <button className="btn secondary" type="button" onClick={() => void os.reload()}>
          Refresh
        </button>
      </div>

      <Subsection label="Status" hint="Programs & device clock">
        <SprinklerStatus snapshot={os.snapshot} />
      </Subsection>

      <Subsection label="Control" hint="Manual run / stop">
        <SprinklerControl
          snapshot={os.snapshot}
          busySid={os.busySid}
          stationBusy={os.stationBusy}
          actionError={os.actionError && !os.modalOpen ? os.actionError : null}
          onStop={(sid) => void os.stopStation(sid)}
          onRun={os.openRunModal}
        />
      </Subsection>

      <Subsection label="History" hint="Device log, last 7 days">
        <SprinklerHistory
          snapshot={os.snapshot}
          runLog={os.runLog}
          logError={os.logError}
          loggingBusy={os.loggingBusy}
          onToggleLogging={(en) => void os.toggleLogging(en)}
        />
      </Subsection>

      <details className="detailsBlock">
        <summary>Raw Open Sprinkler JSON</summary>
        {os.snapshot.raw ? (
          <pre className="pre small" style={{ marginTop: 10 }}>
            {formatJson(os.snapshot.raw)}
          </pre>
        ) : (
          <div className="muted">No raw payload.</div>
        )}
      </details>

      {os.modalOpen ? (
        <RunStationModal
          station={os.modalOpen}
          seconds={os.modalSeconds}
          loading={os.modalLoading}
          error={os.actionError}
          onSecondsChange={os.setModalSeconds}
          onConfirm={() => void os.confirmRun()}
          onClose={os.closeModal}
        />
      ) : null}
    </Section>
  );
}
