import type { OpenSprinklerProgramSummary } from "../types";

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;

function parseClockMinutes(schedule: string): number[] {
  const out: number[] = [];
  const re = /(\d{1,2}):(\d{2})\s*(AM|PM)/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(schedule)) !== null) {
    let h = Number(m[1]);
    const min = Number(m[2]);
    const ap = m[3].toUpperCase();
    if (ap === "PM" && h < 12) h += 12;
    if (ap === "AM" && h === 12) h = 0;
    out.push(h * 60 + min);
  }
  return [...new Set(out)].sort((a, b) => a - b);
}

function parseWeekdays(schedule: string): number[] | "all" | null {
  if (/every day/i.test(schedule)) return "all";
  const found: number[] = [];
  for (let i = 0; i < 7; i++) {
    if (schedule.includes(DAY_NAMES[i])) found.push(i);
  }
  return found.length ? found : null;
}

function stationInProgram(stationName: string, program: OpenSprinklerProgramSummary): boolean {
  if (!program.enabled || !program.watering) return false;
  const w = program.watering.toLowerCase();
  const n = stationName.toLowerCase();
  return w.includes(n);
}

/** Best-effort next fixed clock time from human schedule strings. */
export function estimateNextScheduledRun(
  stationName: string,
  programs: OpenSprinklerProgramSummary[],
  now: Date,
): Date | null {
  let best: Date | null = null;

  for (const p of programs) {
    if (!stationInProgram(stationName, p) || !p.schedule) continue;
    const times = parseClockMinutes(p.schedule);
    if (!times.length) continue;
    const days = parseWeekdays(p.schedule);

    for (let offset = 0; offset < 14; offset++) {
      const d = new Date(now);
      d.setDate(d.getDate() + offset);
      d.setSeconds(0, 0);

      const dow = d.getDay();
      if (days !== "all" && days !== null && !days.includes(dow)) continue;

      for (const mins of times) {
        const candidate = new Date(d);
        candidate.setHours(Math.floor(mins / 60), mins % 60, 0, 0);
        if (candidate.getTime() <= now.getTime()) continue;
        if (!best || candidate.getTime() < best.getTime()) best = candidate;
      }
    }
  }

  return best;
}

export function scheduleHintForStation(
  stationName: string,
  programs: OpenSprinklerProgramSummary[],
): string | null {
  const lines: string[] = [];
  for (const p of programs) {
    if (!stationInProgram(stationName, p) || !p.schedule) continue;
    lines.push(`${p.name}: ${p.schedule}`);
  }
  if (!lines.length) return null;
  return lines[0];
}
