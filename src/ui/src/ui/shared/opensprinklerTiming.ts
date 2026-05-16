import type {
  OpenSprinklerLogResponse,
  OpenSprinklerProgramSummary,
  OpenSprinklerSnapshotConfigured,
  OpenSprinklerStationSummary,
} from "../types";
import { formatDurationSeconds } from "./format";
import { estimateNextScheduledRun, scheduleHintForStation } from "./opensprinklerSchedule";
import { formatTimeAndRelative } from "./relativeTime";

export type TimingCell = {
  primary: string;
  secondary?: string;
  time?: string;
  relative?: string;
  emphasis?: boolean;
};

export type StationTimingRow = {
  id: number;
  name: string;
  current: TimingCell;
  last: TimingCell;
  next: TimingCell;
};

function programName(programs: OpenSprinklerProgramSummary[], programIdx: number): string {
  const p = programs.find((x) => x.id === programIdx);
  return p?.name ?? `Program ${programIdx + 1}`;
}

function deviceNow(devt: unknown): Date {
  const n = Number(devt);
  if (Number.isFinite(n) && n > 0) return new Date(n * 1000);
  return new Date();
}

function lastRunByStation(
  runLog: OpenSprinklerLogResponse | null | undefined,
): Map<number, { endEpoch: number; programName: string; durationLabel: string }> {
  const map = new Map<number, { endEpoch: number; programName: string; durationLabel: string }>();
  if (!runLog?.runs.length) return map;
  for (const row of runLog.runs) {
    if (row.kind !== "run") continue;
    const prev = map.get(row.station_id);
    if (!prev || row.end_epoch > prev.endEpoch) {
      map.set(row.station_id, {
        endEpoch: row.end_epoch,
        programName: row.program_name,
        durationLabel: row.duration_label,
      });
    }
  }
  return map;
}

function psRow(ps: unknown, stationId: number): [number, number, number] | null {
  if (!Array.isArray(ps) || stationId >= ps.length) return null;
  const row = ps[stationId];
  if (!Array.isArray(row) || row.length < 3) return null;
  const pid = Number(row[0]);
  const rem = Number(row[1]);
  const start = Number(row[2]);
  if (!Number.isFinite(pid)) return null;
  return [pid, rem, start];
}

function buildLastCell(
  station: OpenSprinklerStationSummary,
  lastRuns: Map<number, { endEpoch: number; programName: string; durationLabel: string }>,
  lrun: unknown,
  programs: OpenSprinklerProgramSummary[],
  now: Date,
): TimingCell {
  const fromLog = lastRuns.get(station.id);
  if (fromLog) {
    const at = new Date(fromLog.endEpoch * 1000);
    const { time, relative } = formatTimeAndRelative(at, now);
    return {
      primary: fromLog.programName,
      secondary: fromLog.durationLabel,
      time,
      relative,
    };
  }

  if (Array.isArray(lrun) && lrun.length >= 4 && Number(lrun[0]) === station.id) {
    const endEpoch = Number(lrun[3]);
    if (Number.isFinite(endEpoch)) {
      const at = new Date(endEpoch * 1000);
      const { time, relative } = formatTimeAndRelative(at, now);
      return {
        primary: programName(programs, Number(lrun[1])),
        secondary: formatDurationSeconds(Number(lrun[2])),
        time,
        relative,
      };
    }
  }

  return { primary: "—", secondary: "No logged runs" };
}

function buildCurrentCell(
  station: OpenSprinklerStationSummary,
  ps: unknown,
  programs: OpenSprinklerProgramSummary[],
): TimingCell {
  const row = psRow(ps, station.id);
  if (station.on) {
    const rem = row && row[0] > 0 ? formatDurationSeconds(row[1]) : null;
    const prog = row && row[0] > 0 ? programName(programs, row[0] - 1) : null;
    return {
      primary: "Running",
      secondary: [prog, rem ? `${rem} left` : null].filter(Boolean).join(" · ") || undefined,
      emphasis: true,
    };
  }
  if (row && row[0] > 0) {
    return {
      primary: "Queued",
      secondary: programName(programs, row[0] - 1),
    };
  }
  return { primary: "Idle" };
}

function buildNextCell(
  station: OpenSprinklerStationSummary,
  ps: unknown,
  programs: OpenSprinklerProgramSummary[],
  now: Date,
): TimingCell {
  const row = psRow(ps, station.id);

  if (station.on && row && row[0] > 0 && row[1] > 0) {
    const ends = new Date(now.getTime() + row[1] * 1000);
    const { time, relative } = formatTimeAndRelative(ends, now);
    return {
      primary: "Ends",
      secondary: formatDurationSeconds(row[1]) + " left",
      time,
      relative,
    };
  }

  if (row && row[0] > 0 && !station.on) {
    const startEpoch = row[2];
    if (Number.isFinite(startEpoch) && startEpoch > 0) {
      const at = new Date(startEpoch * 1000);
      if (at.getTime() > now.getTime()) {
        const { time, relative } = formatTimeAndRelative(at, now);
        return {
          primary: programName(programs, row[0] - 1),
          secondary: "Queued start",
          time,
          relative,
        };
      }
    }
    if (row[1] > 0) {
      const at = new Date(now.getTime() + row[1] * 1000);
      const { time, relative } = formatTimeAndRelative(at, now);
      return {
        primary: programName(programs, row[0] - 1),
        secondary: "Starts soon",
        time,
        relative,
      };
    }
  }

  const estimated = estimateNextScheduledRun(station.name, programs, now);
  if (estimated) {
    const { time, relative } = formatTimeAndRelative(estimated, now);
    return {
      primary: "Scheduled",
      secondary: scheduleHintForStation(station.name, programs) ?? undefined,
      time,
      relative,
    };
  }

  const hint = scheduleHintForStation(station.name, programs);
  if (hint) {
    return { primary: "Per schedule", secondary: hint };
  }

  return { primary: "—", secondary: "No schedule found" };
}

export function buildStationTimingRows(
  snapshot: OpenSprinklerSnapshotConfigured,
  runLog: OpenSprinklerLogResponse | null | undefined,
): StationTimingRow[] {
  const { stations, programs, controller } = snapshot.summary;
  const now = deviceNow(controller.devt);
  const lastRuns = lastRunByStation(runLog);

  return stations.map((station) => ({
    id: station.id,
    name: station.name,
    current: buildCurrentCell(station, controller.ps, programs),
    last: buildLastCell(station, lastRuns, controller.lrun, programs, now),
    next: buildNextCell(station, controller.ps, programs, now),
  }));
}

/** @deprecated use buildStationTimingRows */
export function decodePs(
  ps: unknown,
  stations: OpenSprinklerStationSummary[],
  programs: OpenSprinklerProgramSummary[],
) {
  const active: Array<{
    stationId: number;
    stationName: string;
    programName: string;
    remainingSeconds: number;
    startEpoch: number;
    kind: "active" | "queued";
  }> = [];
  const queued: typeof active = [];
  if (!Array.isArray(ps)) return { active, queued };

  for (let i = 0; i < ps.length; i++) {
    const row = psRow(ps, i);
    if (!row || row[0] <= 0) continue;
    const station = stations.find((s) => s.id === i);
    const entry = {
      stationId: i,
      stationName: station?.name ?? `Station ${i + 1}`,
      programName: programName(programs, row[0] - 1),
      remainingSeconds: row[1],
      startEpoch: row[2],
      kind: (station?.on ? "active" : "queued") as "active" | "queued",
    };
    if (station?.on) active.push(entry);
    else queued.push(entry);
  }
  return { active, queued };
}
