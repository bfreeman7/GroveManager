import React from "react";
import { describeForwardHealth } from "../shared/forwardHealth";
import type { StatusResponse } from "../types";

type Props = {
  status: StatusResponse | null;
};

export function ForwardHealthBanner({ status }: Props) {
  const view = describeForwardHealth(status);
  if (!view || view.tone === "ok") return null;

  return (
    <div className={`banner forwardHealthBanner banner--${view.tone}`} role="status">
      <div className="forwardHealthBannerTop">
        <span className={`pill ${view.tone === "error" ? "error" : "warning"}`}>{view.pillLabel}</span>
        <strong className="forwardHealthBannerTitle">{view.title}</strong>
      </div>
      <div className="forwardHealthBannerDetail">{view.detail}</div>
      {view.lastSuccessLabel || view.oldestPendingLabel ? (
        <div className="forwardHealthBannerMeta">
          {view.lastSuccessLabel ? <span>Last success {view.lastSuccessLabel}</span> : null}
          {view.oldestPendingLabel ? <span>Oldest pending {view.oldestPendingLabel}</span> : null}
        </div>
      ) : null}
    </div>
  );
}
