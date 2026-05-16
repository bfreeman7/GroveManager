import React from "react";
import { formatJson } from "../shared/format";
import { Section } from "../layout/Section";
import type { ForwardOnceResponse, SystemEvent } from "../types";

type Props = {
  forwardResult: ForwardOnceResponse | null;
  forwardError: string | null;
  allEvents: SystemEvent[];
};

export function DiagnosticsSection({ forwardResult, forwardError, allEvents }: Props) {
  const hasForward = Boolean(forwardResult || forwardError);
  const hasEvents = allEvents.length > 0;

  if (!hasForward && !hasEvents) {
    return null;
  }

  return (
    <details className="detailsBlock card">
      <summary>Diagnostics</summary>
      <div className="sectionBody" style={{ marginTop: 8 }}>
        {forwardError ? (
          <div style={{ marginBottom: 12 }}>
            <div className="cardTitle">Forward error</div>
            <pre className="pre">{forwardError}</pre>
          </div>
        ) : null}
        {forwardResult ? (
          <div style={{ marginBottom: 12 }}>
            <div className="cardTitle">Forward run result</div>
            <pre className="pre">{formatJson(forwardResult)}</pre>
          </div>
        ) : null}
        {hasEvents ? (
          <div>
            <div className="cardTitle">All recent system events</div>
            <div className="events">
              {allEvents.map((e, idx) => (
                <div className="event" key={`${e.ts}-${idx}`}>
                  <div className="eventTop">
                    <span className={`pill ${e.level}`}>{e.level}</span>
                    <span className="mono">{e.ts}</span>
                    <span className="mono">{e.component}</span>
                    <span className="mono">{e.message}</span>
                  </div>
                  {e.details ? <pre className="pre small">{formatJson(e.details)}</pre> : null}
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </details>
  );
}
