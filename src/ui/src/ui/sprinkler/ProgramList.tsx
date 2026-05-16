import React from "react";
import type { OpenSprinklerProgramSummary } from "../types";

type Props = {
  programs: OpenSprinklerProgramSummary[];
};

export function ProgramList({ programs }: Props) {
  if (!programs.length) {
    return <div className="muted">No programs.</div>;
  }

  return (
    <div className="programList">
      {programs.map((p) => (
        <div className="programRow" key={p.id}>
          <div className="programMain">
            <div className="programTitleRow">
              <span className="programName">{p.name}</span>
              <span className={`pill ${p.enabled ? "success" : "danger"}`}>
                {p.enabled ? "enabled" : "disabled"}
              </span>
              {p.use_weather ? (
                <span className="pill info" title="Uses weather adjustment">
                  weather
                </span>
              ) : null}
            </div>
            {p.schedule ? (
              <div className="programDetail">
                <span className="programDetailLabel">Schedule</span>
                <span>{p.schedule}</span>
              </div>
            ) : null}
            {p.watering ? (
              <div className="programDetail">
                <span className="programDetailLabel">Watering</span>
                <span>{p.watering}</span>
              </div>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}
