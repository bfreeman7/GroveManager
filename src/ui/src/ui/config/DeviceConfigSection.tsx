import React from "react";
import { edgeApiBaseForDisplay } from "../api";
import { Section } from "../layout/Section";
import type { StatusResponse } from "../types";

type Props = {
  status: StatusResponse | null;
  opensprinklerConfigured: boolean;
};

export function DeviceConfigSection({ status, opensprinklerConfigured }: Props) {
  return (
    <Section title="Device configuration">
      <div className="kv">
        <div className="k">Edge API</div>
        <div className="v mono">{edgeApiBaseForDisplay()}</div>
        <div className="k">Open Sprinkler</div>
        <div className="v">{opensprinklerConfigured ? "Configured" : "Not configured"}</div>
        <div className="k">Sift mode</div>
        <div className="v mono">{status?.sift_mode ?? "—"}</div>
        <div className="k">Sift asset</div>
        <div className="v mono">{status?.sift_asset ?? "—"}</div>
      </div>

      <details className="detailsBlock">
        <summary>Advanced paths</summary>
        <div className="kv" style={{ marginTop: 8 }}>
          <div className="k">data_path</div>
          <div className="v mono">{status?.data_path ?? "—"}</div>
          <div className="k">edge_db_path</div>
          <div className="v mono">{status?.edge_db_path ?? "—"}</div>
        </div>
      </details>
    </Section>
  );
}
