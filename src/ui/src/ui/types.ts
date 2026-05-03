export type SystemEvent = {
  ts: string;
  level: string;
  component: string;
  message: string;
  details: unknown | null;
};

export type StatusResponse = {
  data_path: string;
  edge_db_path: string;
  sift_mode: string;
  sift_asset: string;
  pending_forward: number;
  total_measurements_indexed: number;
  recent_events: SystemEvent[];
};

export type ForwardOnceResponse = {
  attempted: number;
  forwarded: number;
  error: string | null;
};

