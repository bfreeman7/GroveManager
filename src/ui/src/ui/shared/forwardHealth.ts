import type { StatusResponse } from "../types";
import { formatTimeAndRelative } from "./relativeTime";

export type ForwardHealthTone = "ok" | "warning" | "error";

export type ForwardHealthView = {
  tone: ForwardHealthTone;
  title: string;
  detail: string;
  pillLabel: string;
  connectivityLabel: string;
  connectivityHint: string;
  failureLabel: string | null;
  lastSuccessLabel: string | null;
  oldestPendingLabel: string | null;
};

function formatStreak(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return s > 0 ? `${m}m ${s}s` : `${m}m`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h < 48) return m > 0 ? `${h}h ${m}m` : `${h}h`;
  const d = Math.floor(h / 24);
  const rh = h % 24;
  return rh > 0 ? `${d}d ${rh}h` : `${d}d`;
}

export function humanizeForwardError(key: string | null | undefined): string {
  if (!key) return "Unknown forward error";
  switch (key) {
    case "dns_resolve_failed:grpc-api.siftstack.com":
      return "Cannot resolve Sift DNS (often Tailscale MagicDNS / internet)";
    case "connectivity_offline:sift_dns":
      return "Sift host unreachable — waiting for internet/DNS";
    case "connect_failed:sift_grpc":
      return "Cannot connect to Sift gRPC";
    case "recv_timeout:sift_grpc":
      return "Sift connection timed out";
    case "ping_timeout:sift_grpc":
      return "Sift ping timed out";
    case "unavailable:sift_grpc":
      return "Sift temporarily unavailable";
    default:
      return key;
  }
}

function reasonTitle(reason: string | null | undefined): string {
  switch (reason) {
    case "connectivity_offline":
      return "Offline — queueing locally";
    case "forward_stale":
      return "Sift sync degraded";
    case "forward_failing":
      return "Sift sync failing";
    default:
      return "Sift sync issue";
  }
}

export function describeForwardHealth(
  status: StatusResponse | null | undefined,
  now: Date = new Date(),
): ForwardHealthView | null {
  const forward = status?.forward;
  if (!forward) return null;

  const pending = status?.pending_forward ?? forward.pending_forward ?? 0;
  const failing = (forward.consecutive_failures ?? 0) > 0;
  const offline = forward.connectivity_ok === false;
  const degraded = Boolean(forward.degraded);

  let tone: ForwardHealthTone = "ok";
  let title = "Sift sync healthy";
  let detail =
    pending === 0
      ? "Queue empty — new readings will forward automatically."
      : `${pending.toLocaleString()} measurement(s) waiting; forwarder is keeping up.`;

  if (offline || forward.reason === "connectivity_offline") {
    tone = "warning";
    title = reasonTitle("connectivity_offline");
    detail = `${humanizeForwardError(forward.last_error ?? "connectivity_offline:sift_dns")}. Local ingest continues; Sift will catch up when the network returns.`;
  } else if (degraded) {
    tone = "error";
    title = reasonTitle(forward.reason);
    detail = humanizeForwardError(forward.last_error);
    if (forward.failure_streak_seconds != null && forward.failure_streak_seconds > 0) {
      detail += ` · failing for ${formatStreak(forward.failure_streak_seconds)}`;
    }
  } else if (failing) {
    tone = "warning";
    title = "Sift sync retrying";
    detail = humanizeForwardError(forward.last_error);
    if (forward.consecutive_failures > 0) {
      detail += ` · ${forward.consecutive_failures} consecutive failure(s)`;
    }
  }

  const connectivityLabel = offline ? "Offline" : forward.connectivity_ok === true ? "Online" : "Unknown";
  const connectivityHint = offline
    ? "DNS probe for Sift host failed"
    : forward.connectivity_ok === true
      ? "Sift host DNS resolves"
      : "Connectivity not reported yet";

  let failureLabel: string | null = null;
  if (failing || degraded) {
    const parts = [humanizeForwardError(forward.last_error)];
    if (forward.consecutive_failures > 0) {
      parts.push(`${forward.consecutive_failures}×`);
    }
    if (forward.failure_streak_seconds != null && forward.failure_streak_seconds >= 60) {
      parts.push(formatStreak(forward.failure_streak_seconds));
    }
    failureLabel = parts.join(" · ");
  }

  let lastSuccessLabel: string | null = null;
  if (forward.last_success_at) {
    const at = new Date(forward.last_success_at);
    if (!Number.isNaN(at.getTime())) {
      const { time, relative } = formatTimeAndRelative(at, now);
      lastSuccessLabel = `${time} (${relative})`;
    }
  }

  let oldestPendingLabel: string | null = null;
  if (status?.oldest_pending_ts) {
    const at = new Date(status.oldest_pending_ts);
    if (!Number.isNaN(at.getTime())) {
      const { time, relative } = formatTimeAndRelative(at, now);
      oldestPendingLabel = `${time} (${relative})`;
    } else {
      oldestPendingLabel = status.oldest_pending_ts;
    }
  }

  const pillLabel =
    tone === "ok" ? "healthy" : tone === "warning" ? (offline ? "offline" : "retrying") : "degraded";

  return {
    tone,
    title,
    detail,
    pillLabel,
    connectivityLabel,
    connectivityHint,
    failureLabel,
    lastSuccessLabel,
    oldestPendingLabel,
  };
}
