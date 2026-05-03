import React from "react";
import { edgeApiBaseForDisplay, forwardRunOnce, getStatus } from "./api";
import type { ForwardOnceResponse, StatusResponse } from "./types";

function formatJson(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

export function App() {
  const [status, setStatus] = React.useState<StatusResponse | null>(null);
  const [statusErr, setStatusErr] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  const [forwardRes, setForwardRes] = React.useState<ForwardOnceResponse | null>(null);
  const [forwardErr, setForwardErr] = React.useState<string | null>(null);

  const loadStatus = React.useCallback(async () => {
    try {
      setStatusErr(null);
      const s = await getStatus();
      setStatus(s);
    } catch (e) {
      setStatus(null);
      setStatusErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  React.useEffect(() => {
    void loadStatus();
    const id = window.setInterval(() => void loadStatus(), 5000);
    return () => window.clearInterval(id);
  }, [loadStatus]);

  async function onRunOnce() {
    setLoading(true);
    setForwardRes(null);
    setForwardErr(null);
    try {
      const r = await forwardRunOnce();
      setForwardRes(r);
      await loadStatus();
    } catch (e) {
      setForwardErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <header className="header">
        <div>
          <div className="title">Grove UI</div>
          <div className="subtitle">Edge service status and forwarding</div>
          <div className="subtitle">
            API: <span className="mono">{edgeApiBaseForDisplay()}</span>
          </div>
        </div>
        <div className="actions">
          <button className="btn" onClick={onRunOnce} disabled={loading}>
            {loading ? "Running…" : "Forward: run once"}
          </button>
          <button className="btn secondary" onClick={() => void loadStatus()}>
            Refresh
          </button>
        </div>
      </header>

      {statusErr ? (
        <section className="card error">
          <div className="cardTitle">API error</div>
          <pre className="pre">{statusErr}</pre>
          <div className="hint">
            Set <code>VITE_EDGE_API_BASE</code> (e.g. <code>http://127.0.0.1:8080</code>) if the UI
            is not served from the same origin as the edge service.
          </div>
        </section>
      ) : null}

      <div className="grid">
        <section className="card">
          <div className="cardTitle">Service</div>
          <div className="kv">
            <div className="k">data_path</div>
            <div className="v mono">{status?.data_path ?? "—"}</div>
            <div className="k">edge_db_path</div>
            <div className="v mono">{status?.edge_db_path ?? "—"}</div>
            <div className="k">sift_mode</div>
            <div className="v mono">{status?.sift_mode ?? "—"}</div>
            <div className="k">sift_asset</div>
            <div className="v mono">{status?.sift_asset ?? "—"}</div>
          </div>
        </section>

        <section className="card">
          <div className="cardTitle">Queue</div>
          <div className="bigNumber">{status?.pending_forward ?? "—"}</div>
          <div className="muted">pending_forward</div>
          <div className="kv" style={{ marginTop: 12 }}>
            <div className="k">total_measurements_indexed</div>
            <div className="v mono">{status?.total_measurements_indexed ?? "—"}</div>
          </div>
        </section>
      </div>

      <section className="card">
        <div className="cardTitle">Forward run result</div>
        {forwardErr ? <pre className="pre">{forwardErr}</pre> : null}
        {forwardRes ? <pre className="pre">{formatJson(forwardRes)}</pre> : <div className="muted">—</div>}
      </section>

      <section className="card">
        <div className="cardTitle">Recent events</div>
        {status?.recent_events?.length ? (
          <div className="events">
            {status.recent_events.map((e, idx) => (
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
        ) : (
          <div className="muted">No events yet.</div>
        )}
      </section>
    </div>
  );
}

