import { rawCall, type BackendResult } from './index';
import type {
  DeadLetters, FiscalStats, LicenseInfo, LocalAuditStatus, LogsResult,
  OrderAuditStatus, ServerStatus, SyncState, TunnelStatus, UpdateStatus,
} from './types';

const S = 1000;
const DEFAULT_TIMEOUT = 15 * S;
const LONG = 10 * 60 * S;
const CLOUD = 120 * S;

/**
 * Every desktop.bridge.Api method the panel calls, with its request timeout.
 * tests/desktop/test_ui_bridge_contract.py checks each key against the Python
 * Api class and the Playwright mock fixtures.
 */
export const METHODS = {
  get_ui_prefs: DEFAULT_TIMEOUT,
  set_ui_prefs: DEFAULT_TIMEOUT,
  get_config: DEFAULT_TIMEOUT,
  save_config: 60 * S,
  export_config: DEFAULT_TIMEOUT,
  import_config: 60 * S,
  run_setup: LONG,
  start_server: 120 * S,
  stop_server: 60 * S,
  flush_database: LONG,
  factory_reset: LONG,
  server_status: DEFAULT_TIMEOUT,
  support_tunnel_status: DEFAULT_TIMEOUT,
  set_support_tunnel_enabled: 30 * S,
  test_server_connection: DEFAULT_TIMEOUT,
  update_status: DEFAULT_TIMEOUT,
  check_updates_only: CLOUD,
  check_updates_now: CLOUD,
  restart_to_update: 30 * S,
  license_status: DEFAULT_TIMEOUT,
  sync_status: DEFAULT_TIMEOUT,
  send_mock_sync: 60 * S,
  fetch_mock_sync: 60 * S,
  cloud_test_connection: CLOUD,
  cloud_pull: CLOUD,
  cloud_force_pull: CLOUD,
  cloud_sync_now: CLOUD,
  cloud_dead_letters: CLOUD,
  cloud_resync_failed: CLOUD,
  local_telegram_audit_status: DEFAULT_TIMEOUT,
  save_local_telegram_audit: 60 * S,
  test_local_telegram_audit: 60 * S,
  order_audit_status: DEFAULT_TIMEOUT,
  set_order_audit_enabled: 30 * S,
  set_order_audit_auto_send: 30 * S,
  send_order_audit_now: CLOUD,
  telegram_test: 60 * S,
  send_fake_notification: 60 * S,
  admin_credentials: DEFAULT_TIMEOUT,
  license_register: 60 * S,
  license_plans: 60 * S,
  license_plan_change: 60 * S,
  license_heartbeat_now: 60 * S,
  license_deactivate: 60 * S,
  fiscal_status: DEFAULT_TIMEOUT,
  fiscal_set_mode: 30 * S,
  fiscal_test: 60 * S,
  app_logs: 30 * S,
} as const;

export type MethodName = keyof typeof METHODS;

type R<T> = BackendResult & Partial<T>;

export interface ResultMap {
  server_status: R<ServerStatus>;
  sync_status: R<{ sync: SyncState }>;
  support_tunnel_status: R<TunnelStatus>;
  set_support_tunnel_enabled: R<TunnelStatus>;
  order_audit_status: R<OrderAuditStatus>;
  set_order_audit_enabled: R<OrderAuditStatus>;
  set_order_audit_auto_send: R<OrderAuditStatus>;
  send_order_audit_now: R<OrderAuditStatus>;
  license_status: R<{ license: LicenseInfo }>;
  update_status: R<UpdateStatus>;
  check_updates_only: R<UpdateStatus>;
  check_updates_now: R<UpdateStatus>;
  fiscal_status: R<{ fiscal: FiscalStats }>;
  fiscal_set_mode: R<{ mode: string }>;
  local_telegram_audit_status: R<LocalAuditStatus>;
  save_local_telegram_audit: R<LocalAuditStatus>;
  test_local_telegram_audit: R<LocalAuditStatus>;
  app_logs: R<LogsResult>;
  cloud_dead_letters: R<DeadLetters>;
  cloud_resync_failed: R<{ requeued: number }>;
  cloud_force_pull: R<{ replay_requested: boolean; will_retry: boolean }>;
  admin_credentials: R<{ email: string; password: string; set: boolean }>;
  get_config: R<{ config: Record<string, string>; secret_keys: string[] }>;
  export_config: R<{ config: Record<string, string>; filename: string }>;
  save_config: R<{ restart_required: boolean }>;
  import_config: R<{ restart_required: boolean; imported: string[] }>;
  get_ui_prefs: R<{ prefs: Record<string, unknown> }>;
  start_server: R<ServerStatus>;
  stop_server: R<ServerStatus>;
  factory_reset: R<{ message: string }>;
  flush_database: R<{ message: string }>;
  license_plans: R<{ data: unknown; status: number }>;
  license_register: R<{ data: { message?: string }; status: number }>;
  license_plan_change: R<{ data: { message?: string }; status: number }>;
}

export type ResultOf<M extends MethodName> = M extends keyof ResultMap ? ResultMap[M] : BackendResult;

export interface ApiOptions {
  timeoutMs?: number;
  signal?: AbortSignal;
}

export function api<M extends MethodName>(method: M, args: unknown[] = [], options: ApiOptions = {}): Promise<ResultOf<M>> {
  return rawCall(method, args, {
    timeoutMs: options.timeoutMs ?? METHODS[method],
    signal: options.signal,
  }) as Promise<ResultOf<M>>;
}

/** A backend/transport failure — `{ok:false}` or a normalized bridge error. */
export function isFailure(result: BackendResult | undefined | null): boolean {
  return !result || result.ok === false;
}

export function errorText(result: BackendResult | undefined | null, fallback: string): string {
  const message = result && typeof result.error === 'string' ? result.error.trim() : '';
  return message || fallback;
}
