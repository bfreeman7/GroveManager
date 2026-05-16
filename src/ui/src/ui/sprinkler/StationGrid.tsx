import React from "react";
import type { OpenSprinklerStationSummary } from "../types";

type Props = {
  stations: OpenSprinklerStationSummary[];
  busySid: number | null;
  stationBusy: boolean;
  onStop: (sid: number) => void;
  onRun: (s: { id: number; name: string }) => void;
};

export function StationGrid({ stations, busySid, stationBusy, onStop, onRun }: Props) {
  if (!stations.length) {
    return <div className="muted">No stations reported.</div>;
  }

  return (
    <div className="stationGrid">
      {stations.map((s) => (
        <div key={s.id} className={`stationCell ${s.on ? "on" : ""}`}>
          <div className="stationCellTop">
            <span className="stationName">{s.name}</span>
            <span className={`pill ${s.on ? "success" : "danger"}`}>{s.on ? "ON" : "off"}</span>
          </div>
          <div className="stationCellActions">
            {s.on ? (
              <button
                type="button"
                className="btn sm danger"
                disabled={busySid === s.id}
                onClick={() => onStop(s.id)}
              >
                {busySid === s.id ? "Stopping…" : "Stop"}
              </button>
            ) : (
              <button
                type="button"
                className="btn sm secondary"
                disabled={stationBusy}
                onClick={() => onRun(s)}
              >
                Run…
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
