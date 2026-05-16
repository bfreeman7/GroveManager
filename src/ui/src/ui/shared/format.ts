export function formatJson(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

export function formatDeviceTime(devt: unknown): string {
  if (devt == null || devt === "") return "—";
  const n = Number(devt);
  if (!Number.isFinite(n)) return String(devt);
  return new Date(n * 1000).toLocaleString();
}

export function formatDurationSeconds(sec: number): string {
  if (!Number.isFinite(sec) || sec <= 0) return "—";
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const r = sec % 60;
  return r > 0 ? `${m}m ${r}s` : `${m}m`;
}
