import type {
  ForwardOnceResponse,
  OpenSprinklerLogResponse,
  OpenSprinklerLoggingBody,
  OpenSprinklerLoggingResponse,
  OpenSprinklerSnapshotResponse,
  OpenSprinklerStationManualBody,
  OpenSprinklerStationManualResponse,
  StatusResponse,
} from "./types";

function apiBase(): string {
  // Examples:
  // - "" (same origin)
  // - "http://127.0.0.1:8080"
  // - "http://orchard-monitor.tailnet.ts.net:8080"
  const raw = (import.meta.env.VITE_EDGE_API_BASE as string | undefined) ?? "";
  return raw.replace(/\/$/, "");
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${apiBase()}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} ${res.statusText}: ${text || "(empty body)"}`);
  }
  return JSON.parse(text) as T;
}

export async function getStatus(): Promise<StatusResponse> {
  return fetchJson<StatusResponse>("/status");
}

export async function forwardRunOnce(): Promise<ForwardOnceResponse> {
  return fetchJson<ForwardOnceResponse>("/admin/forward/run-once", { method: "POST" });
}

export async function getOpenSprinklerSnapshot(): Promise<OpenSprinklerSnapshotResponse> {
  return fetchJson<OpenSprinklerSnapshotResponse>("/integrations/opensprinkler/snapshot");
}

export async function postOpenSprinklerStation(
  body: OpenSprinklerStationManualBody,
): Promise<OpenSprinklerStationManualResponse> {
  return fetchJson<OpenSprinklerStationManualResponse>("/integrations/opensprinkler/station", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getOpenSprinklerLog(histDays = 7): Promise<OpenSprinklerLogResponse> {
  return fetchJson<OpenSprinklerLogResponse>(
    `/integrations/opensprinkler/log?hist=${encodeURIComponent(String(histDays))}`,
  );
}

export async function postOpenSprinklerLogging(
  body: OpenSprinklerLoggingBody,
): Promise<OpenSprinklerLoggingResponse> {
  return fetchJson<OpenSprinklerLoggingResponse>("/integrations/opensprinkler/logging", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function edgeApiBaseForDisplay(): string {
  return apiBase() || "(same-origin)";
}

