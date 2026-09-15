// Mock desktop.bridge.Api responses for every method the panel calls.
// tests/desktop/test_ui_bridge_contract.py requires a FIXTURES entry for each
// key of src/bridge/methods.ts:METHODS.

export type Scenario =
  | 'healthy' | 'booting' | 'stopped' | 'error' | 'unregistered'
  | 'offline-cloud' | 'update-pending' | 'big-logs' | 'empty';

export interface MockState {
  scenario: Scenario;
  running: boolean;
  desiredRunning: boolean;
  djangoReady: boolean;
  lastError: string | null;
  fiscalMode: string;
  prefs: Record<string, unknown>;
  tunnelEnabled: boolean;
  auditEnabled: boolean;
  autoSend: boolean;
  localAudit: Record<string, unknown>;
  startedAt: string;
  now: number;
}

export interface FixtureContext {
  args: unknown[];
  state: MockState;
  /** How many times this method was called before (0-based). */
  call: number;
}

type Fixture = (ctx: FixtureContext) => Record<string, unknown>;

const iso = (state: MockState, offsetSeconds: number) => new Date(state.now + offsetSeconds * 1000).toISOString();

export function initialState(scenario: Scenario, now = Date.now()): MockState {
  const stopped = scenario === 'stopped' || scenario === 'booting' || scenario === 'error' || scenario === 'empty';
  return {
    scenario,
    running: !stopped,
    desiredRunning: !stopped || scenario === 'booting',
    djangoReady: scenario !== 'booting',
    lastError: scenario === 'error' ? 'Address already in use: 0.0.0.0:8000' : null,
    fiscalMode: scenario === 'empty' ? 'off' : 'mock',
    prefs: {},
    tunnelEnabled: scenario !== 'empty',
    auditEnabled: true,
    autoSend: true,
    localAudit: {
      enabled: scenario !== 'empty',
      order_recorded: true,
      order_paid: true,
      shift_reports: true,
      report_format: 'TXT',
      chat_ids: scenario === 'empty' ? [] : ['-1001234567890'],
    },
    startedAt: new Date(now - 3_723_000).toISOString(),
    now,
  };
}

const offline = (s: MockState) => s.scenario === 'offline-cloud';

function serverStatus(s: MockState) {
  return {
    ok: true,
    running: s.running,
    phase: s.running ? 'running' : 'stopped',
    desired_running: s.desiredRunning,
    django_ready: s.djangoReady,
    started_at: s.running ? s.startedAt : null,
    last_error: s.lastError,
    url: 'http://127.0.0.1:8000',
    lan_ip: '192.168.1.20',
    port: 8000,
    workers: {
      heartbeat: { alive: s.running, last_error: null, next_run_in_s: s.running ? 42 : null },
      sync: { alive: s.running, last_error: null },
      pull: { alive: s.running, last_error: null },
    },
    environment: { loaded: true, error: null },
    database: { warning: '', error: null },
  };
}

function localAuditStatus(s: MockState) {
  const la = s.localAudit;
  const chats = (la.chat_ids as string[]) || [];
  const enabled = !!la.enabled;
  return {
    ok: true,
    ...la,
    token_configured: s.scenario !== 'empty',
    chat_count: chats.length,
    configured: enabled && chats.length > 0,
    configuration_state: !enabled ? 'disabled' : chats.length ? 'ready' : 'configuration_required',
    delivery_state: 'ready',
    pending_count: offline(s) ? 4 : 0,
    retrying_count: offline(s) ? 1 : 0,
    last_sent_at: s.scenario === 'empty' ? null : iso(s, -900),
    last_error: offline(s) ? 'Telegram API timeout after 20s' : '',
    worker_alive: s.running,
  };
}

function logEntries(s: MockState, count: number) {
  const levels = ['INFO', 'INFO', 'INFO', 'WARNING', 'ERROR', 'DEBUG'];
  const loggers = ['desktop.server', 'base.sync', 'customers.orders', 'desktop.support_tunnel', 'licensing.heartbeat'];
  const entries = [];
  for (let i = 0; i < count; i++) {
    const level = levels[i % levels.length];
    const ts = new Date(s.now - (count - i) * 7000).toISOString().replace('T', ' ').replace('Z', '').replace('.', ',');
    const message = level === 'ERROR'
      ? `Push batch ${i} failed: ConnectionError('cloud unreachable')\nTraceback (most recent call last):\n  File "base/services/sync/transport.py", line 88, in post\n    raise ConnectionError(url)`
      : level === 'WARNING' ? `Slow response from control center (${1200 + i} ms)` : `Order #${10_000 + i} synced to cloud (entry ${i})`;
    entries.push({ ts, level, logger: loggers[i % loggers.length], message });
  }
  const counts = { total: entries.length, error: 0, warning: 0, info: 0 };
  for (const e of entries) {
    if (e.level === 'ERROR') counts.error += 1;
    else if (e.level === 'WARNING') counts.warning += 1;
    else counts.info += 1;
  }
  return { entries, counts };
}

const CONFIG = {
  BRANCH_ID: 'smartfood-chilonzor',
  DEPLOYMENT_MODE: 'local',
  PORT: '8000',
  CLOUD_SYNC_URL: 'https://cloud.alphapos.uz',
  SYNC_ENABLED: 'True',
  CLOUD_SYNC_TOKEN: '••••••••',
  SUPPORT_TUNNEL_ENABLED: 'True',
  SUPPORT_TUNNEL_HOST: '78.111.90.65',
  SUPPORT_TUNNEL_PORT: '22',
  SUPPORT_TUNNEL_USER: 'alphapos-support',
  SUPPORT_TUNNEL_REMOTE_DB_PORT: '15433',
  SUPPORT_TUNNEL_REMOTE_API_PORT: '18000',
  SUPPORT_TUNNEL_PRIVATE_KEY_B64: '••••••••',
  SUPPORT_TUNNEL_KNOWN_HOST: '[78.111.90.65]:22 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHf0q3p9j2x4oVn7s8Lk1uQy6w5eR0tZbXcVfG2hJkMn',
  LICENSE_CONTROL_CENTER_URL: 'https://cc.alphapos.uz/api',
  ALPHA_POS_UPDATE_URL: 'https://updates.alphapos.uz/desktop',
  ORDER_AUDIT_TELEGRAM_CHAT_IDS: '-1001234567890',
  TELEGRAM_WEBHOOK_SECRET: '••••••••',
  AI_PROVIDER: 'claude',
  ANTHROPIC_API_KEY: '',
  ANTHROPIC_MODEL: '',
  GEMINI_API_KEY: '',
  GEMINI_MODEL: '',
  FISCALIZATION_MODE: 'mock',
  FISCAL_PROVIDER: 'mock',
  FISCAL_TIN: '309876543',
  FISCAL_PROVIDER_URL: '',
  FISCAL_VAT_PERCENT: '12',
  FISCAL_MERCHANT_ID: '',
  FISCAL_SECRET: '',
};
const SECRET_KEYS = ['ANTHROPIC_API_KEY', 'CLOUD_SYNC_TOKEN', 'FISCAL_SECRET', 'GEMINI_API_KEY', 'SUPPORT_TUNNEL_PRIVATE_KEY_B64', 'TELEGRAM_WEBHOOK_SECRET'];

export const FIXTURES: Record<string, Fixture> = {
  get_ui_prefs: ({ state }) => ({ ok: true, prefs: state.prefs }),
  set_ui_prefs: ({ state, args }) => {
    state.prefs = { ...state.prefs, ...((args[0] as object) || {}) };
    return { ok: true, prefs: state.prefs };
  },
  get_config: ({ state }) => ({ ok: true, config: state.scenario === 'empty' ? { BRANCH_ID: '', PORT: '8000' } : { ...CONFIG }, secret_keys: SECRET_KEYS }),
  save_config: ({ state }) => ({ ok: true, restart_required: state.running }),
  export_config: () => ({ ok: true, config: { ...CONFIG }, filename: 'alpha-pos-config-smartfood-chilonzor.json' }),
  import_config: ({ args, state }) => ({ ok: true, imported: Object.keys((args[0] as object) || {}).sort(), restart_required: state.running }),
  run_setup: () => ({ ok: true, logs: ['migrations up to date'] }),
  start_server: ({ state }) => {
    state.running = true;
    state.desiredRunning = true;
    state.djangoReady = true;
    state.lastError = null;
    return serverStatus(state);
  },
  stop_server: ({ state }) => {
    state.running = false;
    state.desiredRunning = false;
    return { ...serverStatus(state), workers_quiescent: true };
  },
  flush_database: () => ({ ok: true, message: 'Database flushed — clean data, same configuration.' }),
  factory_reset: () => ({ ok: true, removed: [], message: 'All data deleted. Close and reopen Alpha POS to set it up fresh.' }),
  server_status: ({ state }) => serverStatus(state),
  support_tunnel_status: ({ state }) => {
    const ready = state.tunnelEnabled && !offline(state);
    return {
      ok: true,
      enabled: state.tunnelEnabled,
      configured: state.scenario !== 'empty',
      ready,
      state: !state.tunnelEnabled ? 'off' : ready ? 'ready' : 'connecting',
      db_ready: ready,
      backend_ready: ready,
      db_status: !state.tunnelEnabled ? 'off' : ready ? 'ready' : 'waiting_for_tunnel',
      backend_status: !state.tunnelEnabled ? 'off' : ready ? 'ready' : 'waiting_for_tunnel',
      db_label: ready ? 'DB Ready' : 'DB Not Ready',
      backend_label: ready ? 'Backend Ready' : 'Backend Not Ready',
      session_verified: ready,
      local_db_query_verified: ready,
      relay_host: '78.111.90.65',
      remote_db: '127.0.0.1:15433',
      remote_api: '127.0.0.1:18000',
      connector_artifact: 'AlphaPOS-Support-Connector.ps1',
      operator_db: '127.0.0.1:25433',
      operator_api: 'http://127.0.0.1:28000',
      operator_readiness_instruction: 'Run the support connector only while DB Ready and Backend Ready are both shown.',
      pinned_host_fingerprint: 'SHA256:q9Vn3x0cXl1pK7m2Yb8tWf4ZsR6dJhE5uAoNgCiLkTs',
      configuration_error: '',
      last_probe_error: offline(state) ? 'Relay 78.111.90.65:22 unreachable (timed out)' : '',
      retry_backoff_seconds: offline(state) ? 30 : 0,
      next_retry_at: offline(state) ? iso(state, 30) : null,
      last_error: '',
    };
  },
  set_support_tunnel_enabled: ({ state, args }) => {
    state.tunnelEnabled = !!args[0];
    return FIXTURES.support_tunnel_status({ state, args: [], call: 0 });
  },
  test_server_connection: ({ state }) => (state.running ? { ok: true, status: 200, body: 'ok' } : { ok: false, error: 'Server is not running' }),
  update_status: ({ state }) => ({
    ok: true,
    version: '1.1.0',
    app_name: 'AlphaPOS',
    enabled: true,
    reason: '',
    frozen: true,
    update_url: 'https://updates.alphapos.uz/desktop',
    pending: state.scenario === 'update-pending',
    last_check_at: iso(state, -3600),
    last_check_ok: true,
    last_check_error: '',
    last_update_at: iso(state, -864_000),
    last_update_version: '1.0.46',
    available: state.scenario === 'update-pending' ? '1.1.1' : null,
    history: state.scenario === 'empty' ? [] : [
      { at: iso(state, -2_592_000), version: '1.0.45' },
      { at: iso(state, -864_000), version: '1.0.46' },
    ],
    active: false,
    phase: 'idle',
    progress: 0,
    message: '',
    bytes_downloaded: 0,
    bytes_total: 0,
    target_version: null,
    retryable: false,
  }),
  check_updates_only: ({ state }) => ({ ok: true, current: '1.1.0', available: state.scenario === 'update-pending' ? '1.1.1' : null, enabled: true }),
  check_updates_now: () => ({ ok: true, started: true }),
  license_status: ({ state }) => ({
    ok: true,
    license: state.scenario === 'unregistered' || state.scenario === 'empty'
      ? { status: 'UNREGISTERED', org_name: '', plan: '', email: '', expires_at: null, last_heartbeat_at: null, balance: null, days_remaining: null, warn: false, last_message: '', control_center_url: '' }
      : {
        status: 'ACTIVE', org_name: 'Smart Food LLC', plan: 'Standard', email: 'owner@smartfood.uz',
        expires_at: iso(state, 200 * 86_400), last_heartbeat_at: iso(state, -300), balance: '1250000.00',
        days_remaining: 200, warn: false, last_message: '', control_center_url: 'https://cc.alphapos.uz/api',
      },
  }),
  sync_status: ({ state }) => ({
    ok: true,
    sync: {
      enabled: state.scenario !== 'empty',
      mode: 'smartfood-chilonzor',
      is_online: !offline(state),
      last_sync: iso(state, -120),
      last_pull_at: iso(state, -60),
      last_pull_error: offline(state) ? 'Cloud pull failed: connection refused (cloud.alphapos.uz:443)' : null,
      pending_count: offline(state) ? 27 : 3,
      failed_count: 0,
      dead_letter_count: offline(state) ? 3 : 0,
      last_error: offline(state) ? 'Cloud push failed: connection refused (cloud.alphapos.uz:443)' : null,
      full_pull_pending: offline(state),
      full_pull_state: offline(state) ? 'pending' : 'not_requested',
      shift_close: offline(state)
        ? { state: 'PENDING', clear: false, pending_count: 1, conflict_count: 0, message: 'Shift #412 close is awaiting cloud acknowledgement.' }
        : { state: 'IDLE', clear: true, pending_count: 0, conflict_count: 0, message: 'No shift close is awaiting cloud acknowledgement.' },
    },
  }),
  send_mock_sync: () => ({ ok: true, model: 'customer', read_back: true }),
  fetch_mock_sync: () => ({ ok: true, unsynced_categories: 0, sample: [] }),
  cloud_test_connection: ({ state }) => (offline(state) ? { ok: false, reachable: false, error: 'unreachable' } : { ok: true, reachable: true, url: 'https://cloud.alphapos.uz', message: 'reachable' }),
  cloud_pull: ({ state }) => (offline(state) ? { ok: false, error: 'Cloud pull failed' } : { ok: true, result: { success: true } }),
  cloud_force_pull: ({ state }) => (offline(state)
    ? { ok: false, error: 'Full cloud replay failed', replay_requested: true, will_retry: true }
    : { ok: true, replay_requested: true, will_retry: false }),
  cloud_sync_now: ({ state }) => (offline(state) ? { ok: false, error: 'Cloud push failed' } : { ok: true, push: { success: true }, pull: { success: true } }),
  cloud_dead_letters: ({ state }) => (offline(state) ? { ok: true, total: 3, by_model: { order: 2, shift: 1 }, cap: 10 } : { ok: true, total: 0, by_model: {}, cap: 10 }),
  cloud_resync_failed: () => ({ ok: true, requeued: 3, push: { success: true } }),
  local_telegram_audit_status: ({ state }) => localAuditStatus(state),
  save_local_telegram_audit: ({ state, args }) => {
    const values = (args[0] as Record<string, unknown>) || {};
    const chats = String(values.chat_ids ?? '').split(/[\s,]+/).filter(Boolean);
    state.localAudit = { ...state.localAudit, ...values, chat_ids: chats };
    delete state.localAudit.bot_token;
    return localAuditStatus(state);
  },
  test_local_telegram_audit: () => ({ ok: true, sent: 1 }),
  order_audit_status: ({ state }) => ({
    ok: true,
    enabled: state.auditEnabled,
    auto_send: state.autoSend,
    delivery_state: offline(state) ? 'error' : !state.auditEnabled ? 'off' : !state.autoSend ? 'paused' : 'delivered',
    order_count: state.scenario === 'empty' ? 0 : 1284,
    record_count: state.scenario === 'empty' ? 0 : 5120,
    bytes: 2_400_000,
    auto_pending_bytes: offline(state) ? 48_000 : 0,
    telegram_configured: state.scenario !== 'empty',
    telegram_chat_count: state.scenario === 'empty' ? 0 : 2,
    formats: ['JSONL', 'JSONL.GZ'],
    last_auto_send_error: offline(state) ? '-1001234567890: Telegram API timeout' : '',
    last_error: '',
  }),
  set_order_audit_enabled: ({ state, args }) => {
    state.auditEnabled = !!args[0];
    return FIXTURES.order_audit_status({ state, args: [], call: 0 });
  },
  set_order_audit_auto_send: ({ state, args }) => {
    state.autoSend = !!args[0];
    return FIXTURES.order_audit_status({ state, args: [], call: 0 });
  },
  send_order_audit_now: () => ({ ok: true, sent: 2, sweep: { captured: 0 } }),
  telegram_test: () => ({ ok: true, error: null }),
  send_fake_notification: () => ({ ok: true, error: null }),
  admin_credentials: ({ state }) => (state.scenario === 'empty'
    ? { ok: true, email: '', password: '', set: false }
    : { ok: true, email: 'admin@alphapos.local', password: 'Xk3-p9Qa-77Lm', set: true }),
  license_register: () => ({ ok: true, status: 201, data: { success: true } }),
  license_plans: ({ state }) => (offline(state)
    ? { ok: false, status: 503, data: {}, error: 'Control center unreachable' }
    : {
      ok: true,
      status: 200,
      data: {
        plans: [
          { id: 'starter', name: 'Starter', price: 150000, currency: 'UZS', period: 'mo', description: '1 PC · local only' },
          { id: 'standard', name: 'Standard', price: 250000, currency: 'UZS', period: 'mo', description: '1 PC · cloud sync + Telegram' },
          { id: 'pro', name: 'Pro', price: 450000, currency: 'UZS', period: 'mo', description: 'Multi-branch · priority support' },
        ],
      },
    }),
  license_plan_change: () => ({ ok: true, status: 201, data: { success: true } }),
  license_heartbeat_now: () => ({ ok: true, status: 200, data: { success: true } }),
  license_deactivate: () => ({ ok: true, output: 'License deactivated' }),
  fiscal_status: ({ state }) => ({ ok: true, fiscal: { mode: state.fiscalMode, provider: 'mock', confirmed: 128, failed: 2 } }),
  fiscal_set_mode: ({ state, args }) => {
    state.fiscalMode = String(args[0]);
    return { ok: true, mode: state.fiscalMode };
  },
  fiscal_test: () => ({ ok: true, fiscal_sign: 'MOCK-5F2A91', qr_url: 'https://ofd.soliq.uz/check?t=mock', fiscal_number: '000128', error: null }),
  app_logs: ({ state, args }) => {
    const source = args[0] === 'error' ? 'error' : 'app';
    const path = `C:\\Users\\Cashier\\AppData\\Local\\AlphaPOS\\logs\\${source}.log`;
    if (state.scenario === 'empty') {
      return { ok: true, source, path, exists: false, entries: [], counts: { total: 0, error: 0, warning: 0, info: 0 } };
    }
    const count = state.scenario === 'big-logs' ? 5000 : 120;
    const { entries, counts } = logEntries(state, count);
    const filtered = source === 'error' ? entries.filter((e) => e.level === 'ERROR') : entries;
    return {
      ok: true, source, path, exists: true, entries: filtered,
      counts: source === 'error' ? { total: filtered.length, error: filtered.length, warning: 0, info: 0 } : counts,
    };
  },
};
