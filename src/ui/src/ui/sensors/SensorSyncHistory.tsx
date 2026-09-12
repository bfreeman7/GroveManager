import React from "react";
import { summarizeForwardEvent } from "../shared/syncEvents";
import { formatRelativeTime } from "../shared/relativeTime";
import type { SystemEvent } from "../types";

const MAX_VISIBLE = 6;

type Props = {
  events: SystemEvent[];
};

export function SensorSyncHistory({ events }: Props) {
  const filtered = events.filter((e) => e.component === "forwarder").slice(0, MAX_VISIBLE);
  const hidden = events.filter((e) => e.component === "forwarder").length - filtered.length;

  if (!filtered.length) {
    return (
      <p className="muted compactHint">
        Forward activity will appear here after the edge service sends batches to Sift.
      </p>
    );
  }

  return (
    <>
      <p className="muted compactHint">
        Recent forward attempts to Sift (newest first). Errors and connectivity changes are
        highlighted; successful batches show how many rows were sent.
      </p>
      <ul className="compactEventList">
        {filtered.map((e, idx) => {
          const at = new Date(e.ts);
          const rel = Number.isNaN(at.getTime()) ? "" : formatRelativeTime(at);
          const isError = e.level === "error";
          const isWarning =
            e.level === "warning" ||
            e.message === "connectivity_lost" ||
            e.message === "connectivity_restored";
          const pillClass = isError ? "error" : isWarning ? "warning" : e.level;
          return (
            <li
              key={`${e.ts}-${idx}`}
              className={`compactEvent ${
                isError ? "compactEvent--error" : isWarning ? "compactEvent--warning" : ""
              }`}
            >
              <span className={`pill ${pillClass}`}>{e.level}</span>
              <span className="compactEventMsg">{summarizeForwardEvent(e)}</span>
              <span className="compactEventWhen" title={e.ts}>
                {rel}
              </span>
            </li>
          );
        })}
      </ul>
      {hidden > 0 ? (
        <p className="muted compactHint">{hidden} older events not shown.</p>
      ) : null}
    </>
  );
}
