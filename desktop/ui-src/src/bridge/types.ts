// Result shapes of desktop/bridge.py:Api methods used by the panel. Fields are
// optional where the backend may omit them; screens must tolerate absence.

export type ServerPhase = 'running' | 'starting' | 'stopping' | 'stopped';

export interface WorkerState {
  alive?: boolean;
  last_error?: string | null;
  next_run_in_s?: number | null;
  last_run_at?: string | null;
}

export interface ServerStatus {
  running: boolean;
  phase?: ServerPhase;
  desired_running?: boolean;
  django_ready?: boolean;
  /** One-line reason while database setup keeps failing (the backend retries). */
  setup_error?: string;
  started_at?: string | null;
  last_error?: string | null;
  url?: string;
  lan_ip?: string;
  port?: number;
  workers?: Record<string, WorkerState>;
  environment?: { loaded?: boolean; error?: string | null; path?: string };
  database?: { warning?: string | null; error?: string | null };
}

export interface ShiftCloseStatus {
  state?: string;
  clear?: boolean;
  pending_count?: number;
  conflict_count?: number;
  message?: string;
}

export interface SyncState {
  enabled?: boolean;
  is_online?: boolean;
  last_sync?: string | null;
  last_pull_at?: string | null;
  last_pull_error?: string | null;
  last_error?: string | null;
  pending_count?: number;
  failed_count?: number;
  dead_letter_count?: number;
  full_pull_pending?: boolean;
  full_pull_state?: string;
  shift_close?: ShiftCloseStatus;
}

export interface TunnelStatus {
  enabled?: boolean;
  configured?: boolean;
  ready?: boolean;
  state?: string;
  db_ready?: boolean;
  backend_ready?: boolean;
  db_status?: string;
  backend_status?: string;
  db_label?: string;
  backend_label?: string;
  session_verified?: boolean;
  local_db_query_verified?: boolean;
  relay_host?: string;
  remote_db?: string;
  remote_api?: string;
  connector_artifact?: string;
  operator_db?: string;
  operator_api?: string;
  operator_readiness_instruction?: string;
  pinned_host_fingerprint?: string;
  configuration_error?: string;
  last_probe_error?: string;
  retry_backoff_seconds?: number;
  next_retry_at?: string | null;
  last_error?: string;
}

export interface OrderAuditStatus {
  enabled?: boolean;
  auto_send?: boolean;
  delivery_state?: string;
  order_count?: number;
  record_count?: number;
  bytes?: number;
  auto_pending_bytes?: number;
  telegram_configured?: boolean;
  telegram_chat_count?: number;
  formats?: string[];
  last_auto_send_error?: string;
  last_error?: string;
  partial?: boolean;
  failed?: Array<{ error?: string }>;
}

export interface LicenseInfo {
  status?: string;
  org_name?: string;
  plan?: string;
  email?: string;
  expires_at?: string | null;
  last_heartbeat_at?: string | null;
  balance?: string | null;
  days_remaining?: number | null;
  warn?: boolean;
  last_message?: string;
  control_center_url?: string;
}

export interface UpdateStatus {
  /** 'shell' when the Tauri desktop app installs updates itself. */
  managed_by?: 'shell';
  /** Shell mode: a verified update that installs on "Restart to update". */
  staged_version?: string | null;
  /** Shell mode: the desktop app is looking for / downloading a version now. */
  checking?: boolean;
  blocked_versions?: string[];
  requested?: boolean;
  version?: string;
  enabled?: boolean;
  reason?: string;
  frozen?: boolean;
  update_url?: string;
  pending?: boolean;
  last_check_at?: string | null;
  last_check_ok?: boolean | null;
  last_check_error?: string | null;
  last_update_at?: string | null;
  last_update_version?: string | null;
  available?: string | null;
  history?: Array<{ at?: string; version?: string }>;
  active?: boolean;
  phase?: string;
  progress?: number;
  message?: string;
  bytes_downloaded?: number;
  bytes_total?: number;
  target_version?: string | null;
  retryable?: boolean;
  busy?: boolean;
  started?: boolean;
}

export interface FiscalStats {
  mode?: string;
  provider?: string;
  confirmed?: number;
  failed?: number;
}

export interface LocalAuditStatus {
  enabled?: boolean;
  order_recorded?: boolean;
  order_paid?: boolean;
  shift_reports?: boolean;
  report_format?: string;
  token_configured?: boolean;
  chat_ids?: string[];
  configuration_state?: string;
  pending_count?: number;
  retrying_count?: number;
  last_sent_at?: string | null;
  last_error?: string;
  worker_alive?: boolean;
  failed?: Array<{ error?: string }>;
}

export interface LogEntry {
  ts: string;
  level: string;
  logger: string;
  message: string;
}

export interface LogsResult {
  source?: string;
  path?: string;
  exists?: boolean;
  entries?: LogEntry[];
  counts?: { total: number; error: number; warning: number; info: number };
}

export interface DeadLetters {
  total?: number;
  by_model?: Record<string, number>;
  cap?: number;
}

export interface Plan {
  id: string;
  name: string;
  price?: unknown;
  currency: string;
  period: string;
  desc: string;
  descKey?: string;
}
