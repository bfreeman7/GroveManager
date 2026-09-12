export type SystemEvent = {
  ts: string;
  level: string;
  component: string;
  message: string;
  details: unknown | null;
};

export type ForwardHealth = {
  ok: boolean;
  degraded: boolean;
  reason: string | null;
  pending_forward: number;
  connectivity_ok?: boolean | null;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_error_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  failure_streak_seconds: number | null;
  total_failures: number;
  total_successes: number;
  success_age_seconds: number | null;
  stale_after_seconds: number;
  restart_after_seconds: number;
};

export type StatusResponse = {
  data_path: string;
  edge_db_path: string;
  sift_mode: string;
  sift_asset: string;
  pending_forward: number;
  oldest_pending_ts?: string | null;
  total_measurements_indexed: number;
  forward?: ForwardHealth;
  recent_events: SystemEvent[];
};

export type ForwardOnceResponse = {
  attempted: number;
  forwarded: number;
  error: string | null;
};

export type OpenSprinklerStationSummary = {
  id: number;
  name: string;
  on: boolean;
};

export type OpenSprinklerProgramSummary = {
  id: number;
  name: string;
  enabled: boolean;
  use_weather: boolean;
  schedule: string;
  watering: string;
  total_watering_seconds: number;
};

export type OpenSprinklerControllerSummary = {
  en?: number;
  lg?: number;
  logging_enabled?: boolean;
  rd?: number;
  devt?: number;
  lrun?: unknown;
  ps?: unknown;
};

export type OpenSprinklerSummary = {
  controller: OpenSprinklerControllerSummary;
  stations: OpenSprinklerStationSummary[];
  programs: OpenSprinklerProgramSummary[];
};

export type OpenSprinklerSnapshotNotConfigured = {
  configured: false;
};

export type OpenSprinklerSnapshotConfigured = {
  configured: true;
  fetched_at: string;
  summary: OpenSprinklerSummary;
  raw: unknown;
};

export type OpenSprinklerSnapshotResponse =
  | OpenSprinklerSnapshotNotConfigured
  | OpenSprinklerSnapshotConfigured;

export type OpenSprinklerStationManualBody = {
  sid: number;
  en: 0 | 1;
  t?: number;
  qo?: number;
  ssta?: number;
};

export type OpenSprinklerStationManualResponse = {
  result: number;
  response: unknown;
};

export type OpenSprinklerRunLogEntry =
  | {
      kind: "run";
      station_id: number;
      station_name: string;
      program_id: number;
      program_name: string;
      duration_seconds: number;
      duration_label: string;
      end_epoch: number;
      end_iso: string;
    }
  | {
      kind: "event";
      label: string;
      duration_seconds: number;
      duration_label: string;
      end_epoch: number;
      end_iso: string;
    };

export type OpenSprinklerLogResponse = {
  hist_days: number;
  fetched_at: string;
  runs: OpenSprinklerRunLogEntry[];
};

export type OpenSprinklerLoggingBody = {
  lg: 0 | 1;
};

export type OpenSprinklerLoggingResponse = {
  lg: number;
  result: number;
  response: unknown;
};

