import React from "react";
import { forwardRunOnce, getStatus } from "../api";
import type { ForwardOnceResponse, StatusResponse } from "../types";

const POLL_MS = 5000;

export function useEdgeStatus() {
  const [status, setStatus] = React.useState<StatusResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [forwardLoading, setForwardLoading] = React.useState(false);
  const [forwardResult, setForwardResult] = React.useState<ForwardOnceResponse | null>(null);
  const [forwardError, setForwardError] = React.useState<string | null>(null);

  const reload = React.useCallback(async () => {
    try {
      setError(null);
      const s = await getStatus();
      setStatus(s);
    } catch (e) {
      setStatus(null);
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  React.useEffect(() => {
    void reload();
    const id = window.setInterval(() => void reload(), POLL_MS);
    return () => window.clearInterval(id);
  }, [reload]);

  const runForwardOnce = React.useCallback(async () => {
    setForwardLoading(true);
    setForwardResult(null);
    setForwardError(null);
    try {
      const r = await forwardRunOnce();
      setForwardResult(r);
      await reload();
    } catch (e) {
      setForwardError(e instanceof Error ? e.message : String(e));
    } finally {
      setForwardLoading(false);
    }
  }, [reload]);

  return {
    status,
    error,
    reload,
    forwardLoading,
    forwardResult,
    forwardError,
    runForwardOnce,
  };
}
