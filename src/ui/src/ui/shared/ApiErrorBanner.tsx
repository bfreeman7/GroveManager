import React from "react";

type Props = {
  message: string;
};

export function ApiErrorBanner({ message }: Props) {
  return (
    <section className="card error">
      <div className="cardTitle">API error</div>
      <pre className="pre">{message}</pre>
      <div className="hint">
        Set <code>VITE_EDGE_API_BASE</code> (e.g. <code>http://127.0.0.1:8080</code>) if the UI is
        not served from the same origin as the edge service.
      </div>
    </section>
  );
}
