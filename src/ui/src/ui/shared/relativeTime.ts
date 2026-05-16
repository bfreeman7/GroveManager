export function formatRelativeTime(target: Date, now: Date = new Date()): string {
  const diffMs = target.getTime() - now.getTime();
  const future = diffMs > 0;
  const absSec = Math.round(Math.abs(diffMs) / 1000);

  if (absSec < 60) return future ? "in <1m" : "just now";

  const absMin = Math.floor(absSec / 60);
  if (absMin < 60) {
    const label = absMin === 1 ? "1m" : `${absMin}m`;
    return future ? `in ${label}` : `${label} ago`;
  }

  const absHr = Math.floor(absMin / 60);
  if (absHr < 48) {
    const label = absHr === 1 ? "1h" : `${absHr}h`;
    return future ? `in ${label}` : `${label} ago`;
  }

  const absDay = Math.floor(absHr / 24);
  const label = absDay === 1 ? "1d" : `${absDay}d`;
  return future ? `in ${label}` : `${label} ago`;
}

export function formatTimeAndRelative(at: Date, now: Date = new Date()): { time: string; relative: string } {
  return {
    time: at.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }),
    relative: formatRelativeTime(at, now),
  };
}
