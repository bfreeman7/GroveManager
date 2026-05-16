import React from "react";
import { LOG_HIST_DAYS } from "./hooks/useOpenSprinkler";
import type { OpenSprinklerLogResponse, OpenSprinklerSnapshotConfigured } from "../types";

type Props = {
  snapshot: OpenSprinklerSnapshotConfigured;
  runLog: OpenSprinklerLogResponse | null;
  logError: string | null;
  loggingBusy: boolean;
  onToggleLogging: (enabled: boolean) => void;
};

function formatLogEnd(endEpoch: number): string {
  return new Date(endEpoch * 1000).toLocaleString();
}

export function SprinklerHistory({
  snapshot,
  runLog,
  logError,
  loggingBusy,
  onToggleLogging,
}: Props) {
  const ctrl = snapshot.summary.controller;
  const loggingEnabled = ctrl.logging_enabled === true;
  const loggingKnown = ctrl.logging_enabled === true || ctrl.logging_enabled === false;

  return (
    <>
      <div className="cardTitleRow" style={{ marginBottom: 8 }}>
        <div className="cardTitle" style={{ fontSize: 14, marginBottom: 0 }}>
          Run history
        </div>
        <div className="operationRow">
          <label className="switch" title="Record runs on the controller (Open Sprinkler lg option)">
            <input
              type="checkbox"
              checked={loggingEnabled}
              disabled={!loggingKnown || loggingBusy}
              onChange={(e) => onToggleLogging(e.target.checked)}
            />
            <span className="switchSlider" />
          </label>
          <span className={`pill ${loggingEnabled ? "success" : "danger"}`}>
            {loggingBusy
              ? "updating…"
              : loggingKnown
                ? loggingEnabled
                  ? "logging on"
                  : "logging off"
                : "unknown"}
          </span>
        </div>
      </div>
      <div className="muted" style={{ marginBottom: 8 }}>
        Last {LOG_HIST_DAYS} days from the device log (<code>/jl</code>).
      </div>
      {logError ? <div className="inlineErr">{logError}</div> : null}
      {runLog?.runs.length ? (
        <div className="runLogList">
          {runLog.runs.slice(0, 50).map((row, idx) =>
            row.kind === "run" ? (
              <div className="runLogRow" key={`run-${row.end_epoch}-${row.station_id}-${idx}`}>
                <span className="runLogWhen">{formatLogEnd(row.end_epoch)}</span>
                <span className="runLogMain">
                  {row.station_name} · {row.program_name} · {row.duration_label}
                </span>
              </div>
            ) : (
              <div className="runLogRow runLogRowEvent" key={`evt-${row.end_epoch}-${idx}`}>
                <span className="runLogWhen">{formatLogEnd(row.end_epoch)}</span>
                <span className="runLogMain">
                  {row.label} · {row.duration_label}
                </span>
              </div>
            ),
          )}
        </div>
      ) : !logError ? (
        <div className="muted">No runs in this window.</div>
      ) : null}
      {runLog && runLog.runs.length > 50 ? (
        <div className="muted" style={{ marginTop: 6 }}>
          Showing 50 of {runLog.runs.length} entries.
        </div>
      ) : null}
    </>
  );
}
