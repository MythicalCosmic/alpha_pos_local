// Screens: Local Telegram audit + Configuration (sectioned grid + import/export
// .env). Wired to the live control bridge.

/* ================= LOCAL OWNER TELEGRAM AUDIT ================= */
const LOCAL_AUDIT_L = {
  en: {
    title: "Local Telegram audit",
    sub: "Owner-facing order and shift evidence sent directly from this restaurant PC to Telegram.",
    transport: "Private local transport",
    token: "Dedicated bot token",
    tokenHintSet: "A protected token is saved. Leave blank to keep it.",
    tokenHintEmpty: "Paste the BotFather token for this install only.",
    chats: "Owner chat IDs",
    chatsHint: "Comma, space, or line separated. Negative group IDs and @channels are supported.",
    rules: "Events and report",
    recorded: "Order recorded",
    recordedD: "Matches the new-order lifecycle after totals settle. No product list.",
    paid: "Order paid",
    paidD: "Final cost, discount, total, exact payment time, cashier, and shift.",
    shift: "Shift-close attachment",
    shiftD: "Bounded UTF-8 file with all shift orders and canonical tender/refund totals.",
    format: "Attachment format",
    master: "Enable direct local delivery",
    masterD: "OFF pauses sending. Pending evidence is retained; re-enable starts cleanly.",
    save: "Save local audit",
    test: "Send direct test",
    sending: "Sending…",
    status: "Delivery status",
    ready: "Ready",
    disabled: "Disabled",
    setup: "Setup required",
    pending: "Pending",
    retrying: "Retrying",
    worker: "Worker",
    running: "Running",
    stopped: "Stopped",
    lastSent: "Last acknowledged",
    never: "Never",
    direct: "Direct transport",
    directV: "Restaurant PC → Telegram",
    privacy: "Separation and privacy",
    privacyD: "This channel has its own bot and recipients. It never falls back to the staff bot or raw order-audit recipients, never routes through AlphaPOS cloud/server, and never includes product lines. The token remains in the protected per-install configuration and is never shown or logged.",
    saved: "Local Telegram audit saved",
    testSent: "Direct Telegram test acknowledged",
  },
  uz: {
    title: "Lokal Telegram auditi",
    sub: "Buyurtma va smena dalillari shu restoran kompyuteridan egaga Telegram orqali bevosita yuboriladi.",
    transport: "Shaxsiy lokal transport",
    token: "Alohida bot tokeni",
    tokenHintSet: "Himoyalangan token saqlangan. Saqlab qolish uchun bo‘sh qoldiring.",
    tokenHintEmpty: "Faqat shu o‘rnatma uchun BotFather tokenini kiriting.",
    chats: "Ega chat ID lari",
    chatsHint: "Vergul, bo‘sh joy yoki yangi qatorda. Manfiy guruh ID va @kanal mumkin.",
    rules: "Hodisalar va hisobot",
    recorded: "Buyurtma qayd etildi",
    recordedD: "Summalar tayyor bo‘lgach yangi buyurtma bosqichiga mos keladi. Mahsulot ro‘yxati yo‘q.",
    paid: "Buyurtma to‘landi",
    paidD: "Yakuniy narx, chegirma, jami, aniq vaqt, kassir va smena.",
    shift: "Smena yopilish fayli",
    shiftD: "Barcha smena buyurtmalari va kanonik to‘lov/qaytarish jamlari bilan cheklangan UTF-8 fayl.",
    format: "Fayl formati",
    master: "Bevosita lokal yuborishni yoqish",
    masterD: "O‘CHIRISH yuborishni pauza qiladi. Kutilayotgan dalil saqlanadi.",
    save: "Lokal auditni saqlash",
    test: "Bevosita test yuborish",
    sending: "Yuborilmoqda…",
    status: "Yuborish holati",
    ready: "Tayyor",
    disabled: "O‘chiq",
    setup: "Sozlash kerak",
    pending: "Kutilmoqda",
    retrying: "Qayta urinish",
    worker: "Jarayon",
    running: "Ishlayapti",
    stopped: "To‘xtagan",
    lastSent: "Oxirgi tasdiq",
    never: "Hech qachon",
    direct: "Bevosita transport",
    directV: "Restoran PC → Telegram",
    privacy: "Ajratish va maxfiylik",
    privacyD: "Bu kanalning alohida boti va qabul qiluvchilari bor. Xodimlar boti yoki xom audit chatlariga o‘tmaydi, AlphaPOS bulut/serveridan foydalanmaydi va mahsulot qatorlarini yubormaydi. Token faqat himoyalangan lokal sozlamada qoladi.",
    saved: "Lokal Telegram auditi saqlandi",
    testSent: "Telegram testi tasdiqlandi",
  },
  ru: {
    title: "Локальный Telegram-аудит",
    sub: "Данные заказов и смен отправляются владельцу прямо с компьютера ресторана в Telegram.",
    transport: "Приватный локальный канал",
    token: "Отдельный токен бота",
    tokenHintSet: "Защищённый токен сохранён. Оставьте поле пустым, чтобы не менять его.",
    tokenHintEmpty: "Вставьте токен BotFather только для этой установки.",
    chats: "Chat ID владельцев",
    chatsHint: "Через запятую, пробел или новую строку. Поддерживаются отрицательные ID групп и @каналы.",
    rules: "События и отчёт",
    recorded: "Заказ записан",
    recordedD: "Соответствует новому заказу после фиксации сумм. Без списка товаров.",
    paid: "Заказ оплачен",
    paidD: "Стоимость, скидка, итог, точное время, кассир и смена.",
    shift: "Файл закрытия смены",
    shiftD: "Ограниченный UTF-8 файл со всеми заказами и каноническими итогами оплат/возвратов.",
    format: "Формат файла",
    master: "Включить прямую локальную отправку",
    masterD: "ВЫКЛ приостанавливает отправку. Уже ожидающие данные сохраняются.",
    save: "Сохранить локальный аудит",
    test: "Отправить прямой тест",
    sending: "Отправка…",
    status: "Статус доставки",
    ready: "Готово",
    disabled: "Выключено",
    setup: "Нужна настройка",
    pending: "Ожидает",
    retrying: "Повторяется",
    worker: "Процесс",
    running: "Работает",
    stopped: "Остановлен",
    lastSent: "Последнее подтверждение",
    never: "Никогда",
    direct: "Прямой транспорт",
    directV: "ПК ресторана → Telegram",
    privacy: "Разделение и приватность",
    privacyD: "У канала отдельный бот и получатели. Он не использует бот персонала или чаты сырого аудита, не проходит через облако/сервер AlphaPOS и не включает позиции заказа. Токен остаётся в защищённой конфигурации установки.",
    saved: "Локальный Telegram-аудит сохранён",
    testSent: "Telegram подтвердил тест",
  },
};

function LocalTelegramAuditScreen() {
  const app = useApp();
  const l = LOCAL_AUDIT_L[app.lang] || LOCAL_AUDIT_L.en;
  const [status, setStatus] = React.useState({
    enabled: false, order_recorded: true, order_paid: true, shift_reports: true,
    report_format: "TXT", chat_ids: [], pending_count: 0, retrying_count: 0,
  });
  const [form, setForm] = React.useState({
    enabled: false, order_recorded: true, order_paid: true, shift_reports: true,
    report_format: "TXT", bot_token: "", chat_ids: "",
  });
  const [busy, setBusy] = React.useState("");
  const [dirty, setDirty] = React.useState(false);
  const hydrated = React.useRef(false);

  const applyStatus = React.useCallback((r, forceHydrate) => {
    if (!r || !r.ok) return;
    setStatus(r);
    if (hydrated.current && !forceHydrate) return;
    setForm((old) => ({
      ...old,
      enabled: !!r.enabled,
      order_recorded: r.order_recorded !== false,
      order_paid: r.order_paid !== false,
      shift_reports: r.shift_reports !== false,
      report_format: r.report_format || "TXT",
      chat_ids: (r.chat_ids || []).join(", "),
      bot_token: "",
    }));
    hydrated.current = true;
    setDirty(false);
  }, []);
  const load = React.useCallback(
    () => api.local_telegram_audit_status().then((r) => applyStatus(r, false)),
    [applyStatus],
  );
  React.useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [load]);
  const set = (key, value) => {
    setDirty(true);
    setForm((old) => ({ ...old, [key]: value }));
  };

  const save = async () => {
    if (busy) return;
    setBusy("save");
    const r = await api.save_local_telegram_audit(form);
    setBusy("");
    if (r && r.ok) { applyStatus(r, true); app.toast(l.saved); }
    else app.toast((r && r.error) || "Save failed");
  };
  const test = async () => {
    if (busy) return;
    setBusy("test");
    const r = await api.test_local_telegram_audit();
    setBusy("");
    if (r && r.ok) app.toast(l.testSent);
    else {
      const first = r && r.failed && r.failed.length ? r.failed[0].error : "";
      app.toast(first || (r && r.error) || "Test failed");
    }
    load();
  };

  const configurationState = status.configuration_state || "disabled";
  const ready = configurationState === "ready";
  const stateLabel = ready ? l.ready : (configurationState === "disabled" ? l.disabled : l.setup);
  const stateTone = ready ? "ok" : (configurationState === "disabled" ? "muted" : "warn");

  const ToggleRow = ({ title, detail, value, field }) => (
    <div className="hstack" style={{ justifyContent: "space-between", gap: 18, padding: "12px 0", borderBottom: "1px solid var(--line)" }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 650, fontSize: 13 }}>{title}</div>
        <div style={{ color: "var(--ink-3)", fontSize: 11.5, marginTop: 3, textWrap: "pretty" }}>{detail}</div>
      </div>
      <Switch on={!!value} onChange={(on) => set(field, on)}></Switch>
    </div>
  );

  return (
    <div className="page" data-screen-label="Local Telegram audit">
      <header className="page-head">
        <h1 className="page-h">{l.title}</h1>
        <p className="page-sub">{l.sub}</p>
      </header>
      <div className="cfg-grid">
        <Card title={l.transport} action={<Badge tone={stateTone} pulse={ready}>{stateLabel}</Badge>}>
          <Field l={l.token} hint={status.token_configured ? l.tokenHintSet : l.tokenHintEmpty}>
            <input
              className="inp mono"
              type="password"
              autoComplete="new-password"
              value={form.bot_token}
              placeholder={status.token_configured ? "••••••••" : "123456:…"}
              onChange={(e) => set("bot_token", e.target.value)}
            ></input>
          </Field>
          <Field l={l.chats} hint={l.chatsHint} style={{ marginTop: 16 }}>
            <textarea
              className="inp mono"
              rows="3"
              value={form.chat_ids}
              placeholder="-1001234567890, @owner_channel"
              onChange={(e) => set("chat_ids", e.target.value)}
              style={{ resize: "vertical", minHeight: 76 }}
            ></textarea>
          </Field>
        </Card>

        <Card title={l.rules}>
          <ToggleRow title={l.master} detail={l.masterD} value={form.enabled} field="enabled"></ToggleRow>
          <ToggleRow title={l.recorded} detail={l.recordedD} value={form.order_recorded} field="order_recorded"></ToggleRow>
          <ToggleRow title={l.paid} detail={l.paidD} value={form.order_paid} field="order_paid"></ToggleRow>
          <ToggleRow title={l.shift} detail={l.shiftD} value={form.shift_reports} field="shift_reports"></ToggleRow>
          <Field l={l.format} style={{ marginTop: 14 }}>
            <Seg
              options={[{ v: "TXT", l: "TXT" }, { v: "MD", l: "Markdown" }]}
              value={form.report_format}
              onChange={(value) => set("report_format", value)}
            ></Seg>
          </Field>
        </Card>

        <Card title={l.status}>
          <div className="kv">
            <KRow l={l.pending} v={status.pending_count || 0} mono></KRow>
            <KRow l={l.retrying} v={status.retrying_count || 0} mono></KRow>
            <KRow l={l.worker} v={status.worker_alive ? l.running : l.stopped}></KRow>
            <KRow l={l.lastSent} v={status.last_sent_at || l.never} mono dim={!status.last_sent_at}></KRow>
            <KRow l={l.direct} v={l.directV}></KRow>
          </div>
          {status.last_error ? <div style={{ color: "var(--danger)", fontSize: 12, marginTop: 12, wordBreak: "break-word" }}>{status.last_error}</div> : null}
          <div className="hstack" style={{ marginTop: 16, flexWrap: "wrap" }}>
            <Btn variant="primary" icon="check" disabled={!!busy} onClick={save}>{busy === "save" ? l.sending : (l.save + (dirty ? " *" : ""))}</Btn>
            <Btn variant="ghost" icon="send" disabled={!!busy || !ready} onClick={test}>{busy === "test" ? l.sending : l.test}</Btn>
          </div>
        </Card>

        <Card title={l.privacy}>
          <p style={{ margin: 0, color: "var(--ink-2)", fontSize: 13, lineHeight: 1.65, textWrap: "pretty" }}>{l.privacyD}</p>
        </Card>
      </div>
    </div>
  );
}

/* ================= CONFIGURATION ================= */
// Sectioned layout mirroring config_store.CONFIG_FIELDS. Values + which keys are
// secret come from api.get_config(); save/import/export round-trip the .env.
const CFG_SECTIONS = [
  { t: "cfg.general", fields: [["BRANCH_ID", "text"], ["DEPLOYMENT_MODE", ["local", "cloud"]], ["PORT", "text"]] },
  { t: "cfg.sync", fields: [["CLOUD_SYNC_URL", "text"], ["SYNC_ENABLED", ["True", "False"]], ["CLOUD_SYNC_TOKEN", "secret"]] },
  { t: "cfg.support", hint: "cfg.supportHint", fields: [["SUPPORT_TUNNEL_ENABLED", ["False", "True"]], ["SUPPORT_TUNNEL_HOST", "text"], ["SUPPORT_TUNNEL_PORT", "text"], ["SUPPORT_TUNNEL_USER", "text"], ["SUPPORT_TUNNEL_REMOTE_DB_PORT", "text"], ["SUPPORT_TUNNEL_REMOTE_API_PORT", "text"], ["SUPPORT_TUNNEL_PRIVATE_KEY_B64", "secret"], ["SUPPORT_TUNNEL_KNOWN_HOST", "text"]] },
  { t: "cfg.licensing", fields: [["LICENSE_CONTROL_CENTER_URL", "text"], ["ALPHA_POS_UPDATE_URL", "text"]] },
  { t: "cfg.telegram", fields: [["ORDER_AUDIT_TELEGRAM_CHAT_IDS", "text"], ["TELEGRAM_WEBHOOK_SECRET", "secret"]] },
  { t: "cfg.ai", fields: [["AI_PROVIDER", ["claude", "gemini"]], ["ANTHROPIC_API_KEY", "secret"], ["ANTHROPIC_MODEL", "text"], ["GEMINI_API_KEY", "secret"], ["GEMINI_MODEL", "text"]] },
  { t: "cfg.fiscal", hint: "cfg.fiscalHint", fields: [["FISCALIZATION_MODE", ["off", "mock", "sandbox", "live"]], ["FISCAL_PROVIDER", ["mock", "multikassa"]], ["FISCAL_TIN", "text"], ["FISCAL_PROVIDER_URL", "text"], ["FISCAL_VAT_PERCENT", "text"], ["FISCAL_MERCHANT_ID", "text"], ["FISCAL_SECRET", "secret"]] },
];

function ConfigScreen() {
  const app = useApp();
  const { t } = app;
  const [vals, setVals] = React.useState({});
  const [secrets, setSecrets] = React.useState([]);
  const fileRef = React.useRef(null);

  const load = React.useCallback(() => {
    api.get_config().then((r) => {
      if (r && r.ok) { setVals(r.config || {}); setSecrets(r.secret_keys || []); }
    });
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const set = (k, v) => setVals((o) => ({ ...o, [k]: v }));
  const isSecret = (k) => secrets.indexOf(k) >= 0;

  const save = () => api.save_config(vals).then((r) => app.toast(r && r.ok ? t("cfg.savedToast") + (r.restart_required ? " · " + t("cfg.restart") : "") : (r && r.error) || "Failed"));

  const exportEnv = async () => {
    const r = await api.export_config();
    if (!r || !r.ok) { app.toast("Export failed"); return; }
    const lines = ["# Alpha POS — exported configuration"];
    Object.keys(r.config).sort().forEach((k) => lines.push(k + "=" + (r.config[k] == null ? "" : r.config[k])));
    try {
      const blob = new Blob([lines.join("\n") + "\n"], { type: "text/plain" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = r.filename || "alpha-pos.env";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    } catch (e) {}
    app.toast(t("cfg.exported"));
  };

  const onImportFile = (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const parsed = parseConfigImport(
        String(reader.result || ""),
        Object.keys(vals || {}),
      );
      if (!parsed.ok) {
        app.toast(parsed.error || "Invalid configuration file");
        return;
      }
      api.import_config(parsed.data).then((r) => {
        if (r && r.ok) { app.toast(t("cfg.imported")); load(); } else app.toast((r && r.error) || "Import failed");
      });
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  const renderField = (key, type) => {
    if (Array.isArray(type)) {
      return (
        <Field l={key} key={key}>
          <select className="inp" value={vals[key] != null ? vals[key] : type[0]} onChange={(e) => set(key, e.target.value)}>
            {type.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </Field>
      );
    }
    const secret = type === "secret" || isSecret(key);
    return (
      <Field l={key} key={key}>
        <input className="inp mono" type={secret ? "password" : "text"} value={vals[key] != null ? vals[key] : ""} placeholder={secret ? "•••••••• (blank keeps it)" : ""} onChange={(e) => set(key, e.target.value)}></input>
      </Field>
    );
  };

  return (
    <div className="page" data-screen-label="Configuration">
      <header className="page-head" style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div>
          <h1 className="page-h">{t("cfg.title")}</h1>
          <p className="page-sub">{t("cfg.sub")}</p>
        </div>
        <div className="hstack">
          <input type="file" accept=".env,.json,text/plain,application/json" ref={fileRef} style={{ display: "none" }} onChange={onImportFile}></input>
          <Btn variant="ghost" icon="upload" onClick={() => fileRef.current && fileRef.current.click()}>{t("cfg.import")}</Btn>
          <Btn variant="ghost" icon="download" onClick={exportEnv}>{t("cfg.export")}</Btn>
          <Btn variant="primary" onClick={save}>{t("cfg.saveBtn")}</Btn>
        </div>
      </header>

      <div className="cfg-grid">
        {CFG_SECTIONS.map((sec) => (
          <Card title={t(sec.t)} key={sec.t}>
            {sec.hint ? <p style={{ margin: "0 0 14px", color: "var(--ink-3)", fontSize: 12.5 }}>{t(sec.hint)}</p> : null}
            <div className={sec.fields.length > 1 ? "g2" : "stack"} style={{ gap: 14 }}>
              {sec.fields.map(([k, ty]) => renderField(k, ty))}
            </div>
          </Card>
        ))}

        <Card title={t("cfg.flushT")} tone="warn">
          <p style={{ margin: "0 0 16px", color: "var(--ink-2)", fontSize: 13, textWrap: "pretty" }}>{t("cfg.flushD")}</p>
          <ConfirmBtn variant="warn" icon="refresh" label={t("cfg.flushBtn")} onConfirm={() => api.flush_database(true).then((r) => app.toast(r && r.ok ? t("cfg.flushed") : (r && r.error) || "Failed"))}></ConfirmBtn>
        </Card>

        <Card title={t("cfg.dangerT")} tone="danger">
          <p style={{ margin: "0 0 16px", color: "var(--ink-2)", fontSize: 13, textWrap: "pretty" }}>{t("cfg.dangerD")}</p>
          <ConfirmBtn variant="danger" icon="trash" label={t("cfg.dangerBtn")} onConfirm={() => api.factory_reset(true).then((r) => app.toast(r && r.ok ? (r.message || "Done") : (r && r.error) || "Failed"))}></ConfirmBtn>
        </Card>
      </div>
    </div>
  );
}

Object.assign(window, { LocalTelegramAuditScreen, ConfigScreen });
