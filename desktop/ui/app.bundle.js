/* AlphaPOS desktop UI — generated; do not edit directly.
 * Run: node tools/compile_desktop_ui.js
 * source-sha256: 073cc621b911e9d079c145ddfe169f5bbb4841a0bd17adfccdac95f05face0e3
 */
(function () {
'use strict';

/* source: app/bridge.js */
// Bridge to the local control server. `api.<method>(...args)` POSTs to
// /api/<method> with the args as a JSON array and resolves with the JSON
// result. The per-launch control token is required on every call. Never
// throws — a transport failure resolves to {ok:false, error}.
(function () {
  var TOKEN = window.__CONTROL_TOKEN__ || "";
  window.api = new Proxy({}, {
    get: function (_, name) {
      return function () {
        var args = Array.prototype.slice.call(arguments);
        return fetch("/api/" + name, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Control-Token": TOKEN },
          body: JSON.stringify(args),
        })
          .then(function (r) { return r.json(); })
          .catch(function (e) { return { ok: false, error: String(e) }; });
      };
    },
  });
})();

/* source: app/i18n.js */
// Alpha POS Backend — translations (EN / UZ / RU)
window.I18N = {
  en: {
    "nav.dashboard": "Dashboard",
    "nav.license": "License & Subscription",
    "nav.notifications": "Notifications",
    "nav.config": "Configuration",
    "nav.tests": "Tests",
    "nav.fiscal": "Fiscalization",
    "side.version": "v1.0 · single-PC install",
    "common.save": "Save",
    "common.saved": "Saved",
    "common.run": "Run",
    "common.runAll": "Run all",
    "common.running": "Running…",
    "common.copy": "Copy",
    "common.copied": "Copied to clipboard",
    "common.preview": "Preview",
    "common.hidePreview": "Hide preview",
    "common.enabled": "Enabled",
    "common.online": "Online",
    "common.offline": "Offline",
    "common.active": "Active",
    "common.unregistered": "Unregistered",
    "common.yes": "yes",
    "common.no": "no",
    "common.none": "none",
    "common.justNow": "just now",
    "common.minAgo": "min ago",
    "common.days": "days",
    "common.confirm": "Click again to confirm",
    "common.manage": "Manage",
    "dash.title": "Dashboard",
    "dash.sub": "Your local POS server, at a glance.",
    "dash.serverOff": "Server stopped",
    "dash.serverOffSub": "Press to start serving this point of sale",
    "dash.serverOn": "Server running",
    "dash.serverOnSub": "Press to stop the server",
    "dash.starting": "Starting…",
    "dash.stopping": "Stopping…",
    "dash.local": "Local",
    "dash.network": "Network",
    "dash.port": "Port",
    "dash.uptime": "Uptime",
    "dash.heartbeat": "Heartbeat — control center",
    "dash.controlCenter": "Control center",
    "dash.lastBeat": "Last heartbeat",
    "dash.nextBeat": "Next beat in",
    "dash.pending": "Pending records",
    "dash.lastError": "Last error",
    "dash.syncNow": "Sync now",
    "dash.license": "License",
    "dash.balance": "Account balance",
    "dash.plan": "Plan",
    "dash.org": "Organization",
    "dash.expires": "Expires",
    "dash.daysLeft": "days left",
    "dash.registerNow": "Register now",
    "dash.fiscal": "Fiscalization",
    "dash.mode": "Mode",
    "dash.provider": "Provider",
    "dash.confirmedFailed": "Confirmed / failed",
    "dash.signin": "POS sign-in (this PC)",
    "dash.adminEmail": "Admin email",
    "dash.password": "Password",
    "dash.showPwd": "Show",
    "dash.hidePwd": "Hide",
    "lic.title": "License & Subscription",
    "lic.sub": "Register this install, choose a plan, and manage the license.",
    "lic.current": "Current status",
    "lic.status": "Status",
    "lic.heartbeat": "Last heartbeat",
    "lic.syncNow": "Sync now (heartbeat)",
    "lic.register": "Register online",
    "lic.email": "Email",
    "lic.plan": "Plan",
    "lic.loadPlans": "Load plans",
    "lic.selectPlan": "— select a plan —",
    "lic.registerBtn": "Register",
    "lic.registered": "License activated",
    "lic.needsUrl": "Uses the control-center URL from Configuration.",
    "lic.offline": "Activate offline (interim)",
    "lic.orgName": "Organization",
    "lic.expiresLbl": "Expires",
    "lic.expiresHint": "Leave blank for perpetual",
    "lic.activate": "Activate offline",
    "lic.deactivate": "Deactivate",
    "lic.deactivated": "License deactivated",
    "ntf.title": "Notifications",
    "ntf.sub": "Telegram bot configuration and the message layouts sent to staff.",
    "ntf.telegram": "Telegram (admin)",
    "ntf.enable": "Staff notifications",
    "ntf.enableHint": "Send order, shift and HR alerts to staff on Telegram",
    "ntf.botToken": "Bot token",
    "ntf.botTokenHint": "From @BotFather — leave blank to keep the current one",
    "ntf.chatIds": "Chat IDs",
    "ntf.chatIdsHint": "Comma-separated staff / admin chats that receive alerts",
    "ntf.brand": "Brand name",
    "ntf.saveTg": "Save Telegram settings",
    "ntf.sendTest": "Send test message",
    "ntf.testSent": "Test message sent",
    "ntf.tokenStatus": "Bot token configured · 4 chat IDs",
    "ntf.layouts": "Message layouts",
    "ntf.layoutsHint": "Edit how each notification reads. Use only {named} placeholders.",
    "cfg.title": "Configuration",
    "cfg.sub": "This business's own settings & fiscal identity. Stored locally in .env.",
    "cfg.general": "General",
    "cfg.licensing": "Licensing",
    "cfg.sync": "Sync (cloud)",
    "cfg.telegram": "Telegram webhook",
    "cfg.ai": "AI assistant & forecast",
    "cfg.fiscal": "Fiscalization",
    "cfg.fiscalHint": "Your TIN — leave mode off to bypass for v1",
    "cfg.saveBtn": "Save configuration",
    "cfg.savedToast": "Configuration saved",
    "cfg.flushT": "Flush database",
    "cfg.flushD": "Delete all data — orders, products, users, shifts — and start on a clean, empty database. Your configuration (sync, Telegram, license) is kept.",
    "cfg.flushBtn": "Flush database",
    "cfg.flushed": "Database flushed",
    "cfg.dangerT": "Danger zone",
    "cfg.dangerD": "Permanently delete everything — database, settings, login, logs and uploads — for a clean reinstall. This cannot be undone.",
    "cfg.dangerBtn": "Delete all data & reset",
    "tests.title": "Tests",
    "tests.sub": "Everything self-contained — no real customer data needed.",
    "tests.local": "Local",
    "tests.cloud": "Cloud sync",
    "tests.cloudHint": "Requires sync settings in Configuration. While the server runs with sync enabled, records flow automatically; these run it immediately.",
    "tests.t1": "Server connection",
    "tests.t1d": "Ping the local POS server",
    "tests.t2": "Send mock sync data",
    "tests.t2d": "Loopback through the sync receiver",
    "tests.t3": "Get mock sync data",
    "tests.t3d": "Read unsynced records back",
    "tests.t4": "Telegram bot",
    "tests.t4d": "Send a test message via the bot",
    "tests.t5": "Fake notification",
    "tests.t5d": "Simulate an order-paid alert",
    "tests.t6": "Fiscalization",
    "tests.t6d": "Mock receipt → fiscal sign + QR",
    "tests.t7": "Cloud connection",
    "tests.t7d": "Ping the cloud hub /health over HTTPS",
    "tests.t8": "Sync now (push + pull)",
    "tests.t8d": "Send pending records up, pull changes down",
    "tests.t9": "Create + push test data",
    "tests.t9d": "Generate a test order and push it",
    "tests.recovery": "Recovery",
    "tests.recoveryHint": "Records that fail to send many times in a row are set aside so they don't block the healthy ones — that's why a shift or order can appear \"missing\" in the cloud while it still exists on this till. Confirm the cloud is reachable, then Retry to push them again.",
    "tests.stuckLabel": "Stuck records",
    "tests.stuckNone": "No stuck records — everything reached the cloud.",
    "tests.stuckSome": "stuck and not reaching the cloud",
    "tests.retryStuck": "Retry stuck records",
    "tests.retryDone": "Requeued: {n}",
    "fis.title": "Fiscalization",
    "fis.sub": "Off = fully bypassed (no receipts) — the default for this launch. Mock = local test. Sandbox / Live = real provider when you go fiscal.",
    "fis.mode": "Mode",
    "fis.runTest": "Run test fiscalization",
    "fis.testOk": "Mock receipt signed · QR generated",
    "fis.status": "Status",
    "fis.enabled": "Enabled",
    "fis.provider": "Provider",
    "fis.tin": "TIN set",
    "fis.creds": "Credentials set",
    "fis.cf": "Confirmed / failed",
    "fis.off": "Off",
    "fis.mock": "Mock",
    "fis.sandbox": "Sandbox",
    "fis.live": "Live",
    "lic.plansT": "Plans",
    "lic.plansHint": "Switch any time — billed from your control-center balance.",
    "lic.mo": "/ mo",
    "lic.currentPlan": "Current plan",
    "lic.switch": "Switch plan",
    "lic.p1d": "1 PC · local only",
    "lic.p2d": "1 PC · cloud sync + Telegram",
    "lic.p3d": "Multi-branch · priority support",
    "ntf.recipients": "Recipients",
    "ntf.addChat": "Add",
    "ntf.addPh": "New chat ID…",
    "ntf.labelL": "Label",
    "ntf.chatId": "Chat ID",
    "ntf.receives": "This chat receives",
    "ntf.sendThis": "Send test to this chat",
    "ntf.removeChat": "Remove",
    "ntf.removed": "Recipient removed",
    "ntf.added": "Recipient added",
    "ntf.editTpl": "Edit template",
    "ntf.hideTpl": "Hide template",
    "ev.order_paid": "Order paid",
    "ev.order_paidD": "Each time a sale is closed",
    "ev.daily": "Daily summary",
    "ev.dailyD": "Revenue & shift recap at closing",
    "ev.contract": "Contract expiring",
    "ev.contractD": "HR · hr.contract_expiry",
    "ev.document": "Document expiring",
    "ev.documentD": "HR · hr.document_expiry",
    "ev.system": "System alerts",
    "ev.systemD": "Sync failures, fiscal errors, low disk",
    "cfg.export": "Export .env",
    "cfg.import": "Import .env",
    "cfg.exported": ".env exported",
    "cfg.imported": "Settings imported",
    "tests.passed": "passed"
  },
  uz: {
    "nav.dashboard": "Boshqaruv paneli",
    "nav.license": "Litsenziya va obuna",
    "nav.notifications": "Bildirishnomalar",
    "nav.config": "Sozlamalar",
    "nav.tests": "Testlar",
    "nav.fiscal": "Fiskalizatsiya",
    "side.version": "v1.0 · bitta kompyuter",
    "common.save": "Saqlash",
    "common.saved": "Saqlandi",
    "common.run": "Ishga tushirish",
    "common.runAll": "Hammasini ishga tushirish",
    "common.running": "Bajarilmoqda…",
    "common.copy": "Nusxalash",
    "common.copied": "Nusxalandi",
    "common.preview": "Ko'rib chiqish",
    "common.hidePreview": "Yashirish",
    "common.enabled": "Yoqilgan",
    "common.online": "Onlayn",
    "common.offline": "Oflayn",
    "common.active": "Faol",
    "common.unregistered": "Ro'yxatdan o'tmagan",
    "common.yes": "ha",
    "common.no": "yo'q",
    "common.none": "yo'q",
    "common.justNow": "hozirgina",
    "common.minAgo": "daqiqa oldin",
    "common.days": "kun",
    "common.confirm": "Tasdiqlash uchun yana bosing",
    "common.manage": "Boshqarish",
    "dash.title": "Boshqaruv paneli",
    "dash.sub": "Mahalliy POS serveringiz — bir qarashda.",
    "dash.serverOff": "Server to'xtatilgan",
    "dash.serverOffSub": "Kassani ishga tushirish uchun bosing",
    "dash.serverOn": "Server ishlamoqda",
    "dash.serverOnSub": "Serverni to'xtatish uchun bosing",
    "dash.starting": "Ishga tushmoqda…",
    "dash.stopping": "To'xtatilmoqda…",
    "dash.local": "Mahalliy",
    "dash.network": "Tarmoq",
    "dash.port": "Port",
    "dash.uptime": "Ish vaqti",
    "dash.heartbeat": "Heartbeat — boshqaruv markazi",
    "dash.controlCenter": "Boshqaruv markazi",
    "dash.lastBeat": "Oxirgi heartbeat",
    "dash.nextBeat": "Keyingisi",
    "dash.pending": "Kutilayotgan yozuvlar",
    "dash.lastError": "Oxirgi xato",
    "dash.syncNow": "Hozir sinxronlash",
    "dash.license": "Litsenziya",
    "dash.balance": "Hisob balansi",
    "dash.plan": "Tarif",
    "dash.org": "Tashkilot",
    "dash.expires": "Tugash sanasi",
    "dash.daysLeft": "kun qoldi",
    "dash.registerNow": "Ro'yxatdan o'tish",
    "dash.fiscal": "Fiskalizatsiya",
    "dash.mode": "Rejim",
    "dash.provider": "Provayder",
    "dash.confirmedFailed": "Tasdiqlangan / xato",
    "dash.signin": "POS kirish (shu kompyuter)",
    "dash.adminEmail": "Admin email",
    "dash.password": "Parol",
    "dash.showPwd": "Ko'rsatish",
    "dash.hidePwd": "Yashirish",
    "lic.title": "Litsenziya va obuna",
    "lic.sub": "O'rnatishni ro'yxatdan o'tkazing, tarif tanlang va litsenziyani boshqaring.",
    "lic.current": "Joriy holat",
    "lic.status": "Holat",
    "lic.heartbeat": "Oxirgi heartbeat",
    "lic.syncNow": "Hozir sinxronlash (heartbeat)",
    "lic.register": "Onlayn ro'yxatdan o'tish",
    "lic.email": "Email",
    "lic.plan": "Tarif",
    "lic.loadPlans": "Tariflarni yuklash",
    "lic.selectPlan": "— tarifni tanlang —",
    "lic.registerBtn": "Ro'yxatdan o'tish",
    "lic.registered": "Litsenziya faollashtirildi",
    "lic.needsUrl": "Sozlamalardagi boshqaruv markazi URL'idan foydalanadi.",
    "lic.offline": "Oflayn faollashtirish (vaqtinchalik)",
    "lic.orgName": "Tashkilot",
    "lic.expiresLbl": "Tugash sanasi",
    "lic.expiresHint": "Muddatsiz uchun bo'sh qoldiring",
    "lic.activate": "Oflayn faollashtirish",
    "lic.deactivate": "O'chirish",
    "lic.deactivated": "Litsenziya o'chirildi",
    "ntf.title": "Bildirishnomalar",
    "ntf.sub": "Telegram bot sozlamalari va xodimlarga yuboriladigan xabar shablonlari.",
    "ntf.telegram": "Telegram (admin)",
    "ntf.enable": "Xodimlar bildirishnomalari",
    "ntf.enableHint": "Buyurtma, smena va HR ogohlantirishlarini Telegram orqali xodimlarga yuborish",
    "ntf.botToken": "Bot token",
    "ntf.botTokenHint": "@BotFather'dan — joriy tokenni saqlash uchun bo'sh qoldiring",
    "ntf.chatIds": "Chat ID'lar",
    "ntf.chatIdsHint": "Vergul bilan ajratilgan xodim / admin chatlari",
    "ntf.brand": "Brend nomi",
    "ntf.saveTg": "Telegram sozlamalarini saqlash",
    "ntf.sendTest": "Test xabar yuborish",
    "ntf.testSent": "Test xabar yuborildi",
    "ntf.tokenStatus": "Bot token sozlangan · 4 ta chat ID",
    "ntf.layouts": "Xabar shablonlari",
    "ntf.layoutsHint": "Har bir bildirishnoma matnini tahrirlang. Faqat {nomlangan} o'rinbosarlardan foydalaning.",
    "cfg.title": "Sozlamalar",
    "cfg.sub": "Biznesning shaxsiy sozlamalari va fiskal identifikatori. Lokal .env faylida saqlanadi.",
    "cfg.general": "Umumiy",
    "cfg.licensing": "Litsenziyalash",
    "cfg.sync": "Sinxronlash (bulut)",
    "cfg.telegram": "Telegram webhook",
    "cfg.ai": "AI yordamchi va prognoz",
    "cfg.fiscal": "Fiskalizatsiya",
    "cfg.fiscalHint": "Sizning STIR — v1 uchun rejimni o'chiq qoldiring",
    "cfg.saveBtn": "Sozlamalarni saqlash",
    "cfg.savedToast": "Sozlamalar saqlandi",
    "cfg.flushT": "Bazani tozalash",
    "cfg.flushD": "Barcha ma'lumotlarni — buyurtmalar, mahsulotlar, foydalanuvchilar, smenalar — o'chirib, toza bazadan boshlang. Sozlamalar (sinxronlash, Telegram, litsenziya) saqlanadi.",
    "cfg.flushBtn": "Bazani tozalash",
    "cfg.flushed": "Baza tozalandi",
    "cfg.dangerT": "Xavfli hudud",
    "cfg.dangerD": "Hammasini butunlay o'chirish — baza, sozlamalar, login, loglar va yuklamalar. Buni bekor qilib bo'lmaydi.",
    "cfg.dangerBtn": "Hammasini o'chirish va qayta o'rnatish",
    "tests.title": "Testlar",
    "tests.sub": "Hammasi mustaqil — haqiqiy mijoz ma'lumotlari kerak emas.",
    "tests.local": "Mahalliy",
    "tests.cloud": "Bulutli sinxronlash",
    "tests.cloudHint": "Sozlamalarda sinxronlash sozlangan bo'lishi kerak. Server ishlayotganda yozuvlar avtomatik oqadi; bular darhol ishga tushiradi.",
    "tests.t1": "Server ulanishi",
    "tests.t1d": "Mahalliy POS serverga ping",
    "tests.t2": "Mock sync yuborish",
    "tests.t2d": "Sync qabul qiluvchi orqali loopback",
    "tests.t3": "Mock sync olish",
    "tests.t3d": "Sinxronlanmagan yozuvlarni o'qish",
    "tests.t4": "Telegram bot",
    "tests.t4d": "Bot orqali test xabar yuborish",
    "tests.t5": "Soxta bildirishnoma",
    "tests.t5d": "Buyurtma to'landi signalini simulyatsiya qilish",
    "tests.t6": "Fiskalizatsiya",
    "tests.t6d": "Mock chek → fiskal imzo + QR",
    "tests.t7": "Bulut ulanishi",
    "tests.t7d": "HTTPS orqali bulut /health'ga ping",
    "tests.t8": "Hozir sinxronlash (push + pull)",
    "tests.t8d": "Kutilayotganlarni yuborish, o'zgarishlarni olish",
    "tests.t9": "Test ma'lumot yaratish + yuborish",
    "tests.t9d": "Test buyurtma yaratib, uni yuborish",
    "tests.recovery": "Tiklash",
    "tests.recoveryHint": "Ketma-ket ko'p marta yuborilmagan yozuvlar boshqalarini to'smaslik uchun chetga suriladi — shu sabab smena yoki buyurtma bu kassada turgani holda bulutda \"yo'qolib\" ko'rinishi mumkin. Bulut aloqasini tekshiring va ularni qayta yuborish uchun \"Qayta urinish\" ni bosing.",
    "tests.stuckLabel": "Tiqilib qolgan yozuvlar",
    "tests.stuckNone": "Tiqilib qolgan yozuv yo'q — hammasi bulutga yetdi.",
    "tests.stuckSome": "tiqilib qolgan va bulutga yetmayapti",
    "tests.retryStuck": "Tiqilganlarni qayta yuborish",
    "tests.retryDone": "Navbatga qaytarildi: {n}",
    "fis.title": "Fiskalizatsiya",
    "fis.sub": "O'chiq = to'liq chetlab o'tilgan (cheksiz) — ushbu launch uchun standart. Mock = lokal test. Sandbox / Live = haqiqiy provayder.",
    "fis.mode": "Rejim",
    "fis.runTest": "Test fiskalizatsiyani ishga tushirish",
    "fis.testOk": "Mock chek imzolandi · QR yaratildi",
    "fis.status": "Holat",
    "fis.enabled": "Yoqilgan",
    "fis.provider": "Provayder",
    "fis.tin": "STIR kiritilgan",
    "fis.creds": "Hisob ma'lumotlari kiritilgan",
    "fis.cf": "Tasdiqlangan / xato",
    "fis.off": "O'chiq",
    "fis.mock": "Mock",
    "fis.sandbox": "Sandbox",
    "fis.live": "Live",
    "lic.plansT": "Tariflar",
    "lic.plansHint": "Istalgan vaqtda almashtiring — boshqaruv markazi balansidan to'lanadi.",
    "lic.mo": "/ oy",
    "lic.currentPlan": "Joriy tarif",
    "lic.switch": "Tarifni almashtirish",
    "lic.p1d": "1 kompyuter · faqat lokal",
    "lic.p2d": "1 kompyuter · bulut sinxronlash + Telegram",
    "lic.p3d": "Ko'p filial · ustuvor qo'llab-quvvatlash",
    "ntf.recipients": "Qabul qiluvchilar",
    "ntf.addChat": "Qo'shish",
    "ntf.addPh": "Yangi chat ID…",
    "ntf.labelL": "Nomi",
    "ntf.chatId": "Chat ID",
    "ntf.receives": "Bu chat qabul qiladi",
    "ntf.sendThis": "Shu chatga test yuborish",
    "ntf.removeChat": "O'chirish",
    "ntf.removed": "Qabul qiluvchi o'chirildi",
    "ntf.added": "Qabul qiluvchi qo'shildi",
    "ntf.editTpl": "Shablonni tahrirlash",
    "ntf.hideTpl": "Shablonni yashirish",
    "ev.order_paid": "Buyurtma to'landi",
    "ev.order_paidD": "Har bir savdo yopilganda",
    "ev.daily": "Kunlik hisobot",
    "ev.dailyD": "Yopilishda tushum va smena xulosasi",
    "ev.contract": "Shartnoma muddati tugayapti",
    "ev.contractD": "HR · hr.contract_expiry",
    "ev.document": "Hujjat muddati tugayapti",
    "ev.documentD": "HR · hr.document_expiry",
    "ev.system": "Tizim ogohlantirishlari",
    "ev.systemD": "Sinxronlash xatolari, fiskal xatolar, disk joyi",
    "cfg.export": "Eksport .env",
    "cfg.import": "Import .env",
    "cfg.exported": ".env eksport qilindi",
    "cfg.imported": "Sozlamalar import qilindi",
    "tests.passed": "o'tdi"
  },
  ru: {
    "nav.dashboard": "Панель управления",
    "nav.license": "Лицензия и подписка",
    "nav.notifications": "Уведомления",
    "nav.config": "Настройки",
    "nav.tests": "Тесты",
    "nav.fiscal": "Фискализация",
    "side.version": "v1.0 · один ПК",
    "common.save": "Сохранить",
    "common.saved": "Сохранено",
    "common.run": "Запустить",
    "common.runAll": "Запустить все",
    "common.running": "Выполняется…",
    "common.copy": "Копировать",
    "common.copied": "Скопировано",
    "common.preview": "Предпросмотр",
    "common.hidePreview": "Скрыть",
    "common.enabled": "Включено",
    "common.online": "Онлайн",
    "common.offline": "Офлайн",
    "common.active": "Активна",
    "common.unregistered": "Не зарегистрирована",
    "common.yes": "да",
    "common.no": "нет",
    "common.none": "нет",
    "common.justNow": "только что",
    "common.minAgo": "мин назад",
    "common.days": "дней",
    "common.confirm": "Нажмите ещё раз для подтверждения",
    "common.manage": "Управлять",
    "dash.title": "Панель управления",
    "dash.sub": "Ваш локальный POS-сервер — с первого взгляда.",
    "dash.serverOff": "Сервер остановлен",
    "dash.serverOffSub": "Нажмите, чтобы запустить кассу",
    "dash.serverOn": "Сервер работает",
    "dash.serverOnSub": "Нажмите, чтобы остановить сервер",
    "dash.starting": "Запуск…",
    "dash.stopping": "Остановка…",
    "dash.local": "Локально",
    "dash.network": "Сеть",
    "dash.port": "Порт",
    "dash.uptime": "Время работы",
    "dash.heartbeat": "Heartbeat — центр управления",
    "dash.controlCenter": "Центр управления",
    "dash.lastBeat": "Последний heartbeat",
    "dash.nextBeat": "Следующий через",
    "dash.pending": "Ожидающие записи",
    "dash.lastError": "Последняя ошибка",
    "dash.syncNow": "Синхронизировать",
    "dash.license": "Лицензия",
    "dash.balance": "Баланс счёта",
    "dash.plan": "Тариф",
    "dash.org": "Организация",
    "dash.expires": "Истекает",
    "dash.daysLeft": "дней осталось",
    "dash.registerNow": "Зарегистрировать",
    "dash.fiscal": "Фискализация",
    "dash.mode": "Режим",
    "dash.provider": "Провайдер",
    "dash.confirmedFailed": "Подтверждено / ошибки",
    "dash.signin": "Вход в POS (этот ПК)",
    "dash.adminEmail": "Email админа",
    "dash.password": "Пароль",
    "dash.showPwd": "Показать",
    "dash.hidePwd": "Скрыть",
    "lic.title": "Лицензия и подписка",
    "lic.sub": "Зарегистрируйте установку, выберите тариф и управляйте лицензией.",
    "lic.current": "Текущий статус",
    "lic.status": "Статус",
    "lic.heartbeat": "Последний heartbeat",
    "lic.syncNow": "Синхронизировать (heartbeat)",
    "lic.register": "Онлайн-регистрация",
    "lic.email": "Email",
    "lic.plan": "Тариф",
    "lic.loadPlans": "Загрузить тарифы",
    "lic.selectPlan": "— выберите тариф —",
    "lic.registerBtn": "Зарегистрировать",
    "lic.registered": "Лицензия активирована",
    "lic.needsUrl": "Использует URL центра управления из Настроек.",
    "lic.offline": "Офлайн-активация (временная)",
    "lic.orgName": "Организация",
    "lic.expiresLbl": "Истекает",
    "lic.expiresHint": "Оставьте пустым для бессрочной",
    "lic.activate": "Активировать офлайн",
    "lic.deactivate": "Деактивировать",
    "lic.deactivated": "Лицензия деактивирована",
    "ntf.title": "Уведомления",
    "ntf.sub": "Настройки Telegram-бота и шаблоны сообщений для персонала.",
    "ntf.telegram": "Telegram (админ)",
    "ntf.enable": "Уведомления персонала",
    "ntf.enableHint": "Отправлять персоналу уведомления о заказах, сменах и HR в Telegram",
    "ntf.botToken": "Токен бота",
    "ntf.botTokenHint": "От @BotFather — оставьте пустым, чтобы сохранить текущий",
    "ntf.chatIds": "ID чатов",
    "ntf.chatIdsHint": "Через запятую — чаты персонала / админов для оповещений",
    "ntf.brand": "Название бренда",
    "ntf.saveTg": "Сохранить настройки Telegram",
    "ntf.sendTest": "Отправить тест",
    "ntf.testSent": "Тестовое сообщение отправлено",
    "ntf.tokenStatus": "Токен настроен · 4 ID чатов",
    "ntf.layouts": "Шаблоны сообщений",
    "ntf.layoutsHint": "Отредактируйте текст каждого уведомления. Используйте только {именованные} плейсхолдеры.",
    "cfg.title": "Настройки",
    "cfg.sub": "Собственные настройки бизнеса и фискальные данные. Хранятся локально в .env.",
    "cfg.general": "Общие",
    "cfg.licensing": "Лицензирование",
    "cfg.sync": "Синхронизация (облако)",
    "cfg.telegram": "Telegram webhook",
    "cfg.ai": "AI-ассистент и прогноз",
    "cfg.fiscal": "Фискализация",
    "cfg.fiscalHint": "Ваш ИНН — оставьте режим выключенным для v1",
    "cfg.saveBtn": "Сохранить настройки",
    "cfg.savedToast": "Настройки сохранены",
    "cfg.flushT": "Очистить базу",
    "cfg.flushD": "Удалить все данные — заказы, товары, пользователей, смены — и начать с чистой базы. Настройки (синхронизация, Telegram, лицензия) сохраняются.",
    "cfg.flushBtn": "Очистить базу",
    "cfg.flushed": "База очищена",
    "cfg.dangerT": "Опасная зона",
    "cfg.dangerD": "Безвозвратно удалить всё — базу, настройки, логин, логи и загрузки — для чистой переустановки. Это нельзя отменить.",
    "cfg.dangerBtn": "Удалить всё и сбросить",
    "tests.title": "Тесты",
    "tests.sub": "Всё автономно — реальные данные клиентов не нужны.",
    "tests.local": "Локальные",
    "tests.cloud": "Облачная синхронизация",
    "tests.cloudHint": "Сначала настройте синхронизацию в Настройках. Пока сервер работает, записи идут автоматически; эти тесты запускают её сразу.",
    "tests.t1": "Подключение к серверу",
    "tests.t1d": "Пинг локального POS-сервера",
    "tests.t2": "Отправка mock-данных",
    "tests.t2d": "Loopback через приёмник синхронизации",
    "tests.t3": "Получение mock-данных",
    "tests.t3d": "Чтение несинхронизированных записей",
    "tests.t4": "Telegram-бот",
    "tests.t4d": "Отправить тестовое сообщение через бота",
    "tests.t5": "Тестовое уведомление",
    "tests.t5d": "Симуляция оповещения об оплате заказа",
    "tests.t6": "Фискализация",
    "tests.t6d": "Mock-чек → фискальная подпись + QR",
    "tests.t7": "Облачное подключение",
    "tests.t7d": "Пинг облачного /health по HTTPS",
    "tests.t8": "Синхронизировать (push + pull)",
    "tests.t8d": "Отправить ожидающие записи, получить изменения",
    "tests.t9": "Создать + отправить тест-данные",
    "tests.t9d": "Сгенерировать тестовый заказ и отправить",
    "tests.recovery": "Восстановление",
    "tests.recoveryHint": "Записи, которые не удалось отправить много раз подряд, откладываются, чтобы не блокировать остальные — из-за этого смена или заказ могут «пропасть» в облаке, оставаясь на этой кассе. Проверьте связь с облаком и нажмите «Повторить», чтобы отправить их снова.",
    "tests.stuckLabel": "Застрявшие записи",
    "tests.stuckNone": "Нет застрявших записей — всё дошло до облака.",
    "tests.stuckSome": "застряло и не доходит до облака",
    "tests.retryStuck": "Повторить застрявшие",
    "tests.retryDone": "Возвращено в очередь: {n}",
    "fis.title": "Фискализация",
    "fis.sub": "Выкл = полностью отключена (без чеков) — по умолчанию. Mock = локальный тест. Sandbox / Live = реальный провайдер.",
    "fis.mode": "Режим",
    "fis.runTest": "Запустить тестовую фискализацию",
    "fis.testOk": "Mock-чек подписан · QR сгенерирован",
    "fis.status": "Статус",
    "fis.enabled": "Включена",
    "fis.provider": "Провайдер",
    "fis.tin": "ИНН указан",
    "fis.creds": "Учётные данные указаны",
    "fis.cf": "Подтверждено / ошибки",
    "fis.off": "Выкл",
    "fis.mock": "Mock",
    "fis.sandbox": "Sandbox",
    "fis.live": "Live",
    "lic.plansT": "Тарифы",
    "lic.plansHint": "Меняйте в любой момент — списывается с баланса центра управления.",
    "lic.mo": "/ мес",
    "lic.currentPlan": "Текущий тариф",
    "lic.switch": "Сменить тариф",
    "lic.p1d": "1 ПК · только локально",
    "lic.p2d": "1 ПК · облачная синхронизация + Telegram",
    "lic.p3d": "Мульти-филиал · приоритетная поддержка",
    "ntf.recipients": "Получатели",
    "ntf.addChat": "Добавить",
    "ntf.addPh": "Новый chat ID…",
    "ntf.labelL": "Метка",
    "ntf.chatId": "Chat ID",
    "ntf.receives": "Этот чат получает",
    "ntf.sendThis": "Отправить тест в этот чат",
    "ntf.removeChat": "Удалить",
    "ntf.removed": "Получатель удалён",
    "ntf.added": "Получатель добавлен",
    "ntf.editTpl": "Редактировать шаблон",
    "ntf.hideTpl": "Скрыть шаблон",
    "ev.order_paid": "Заказ оплачен",
    "ev.order_paidD": "При каждой закрытой продаже",
    "ev.daily": "Дневная сводка",
    "ev.dailyD": "Выручка и итог смены при закрытии",
    "ev.contract": "Истекает договор",
    "ev.contractD": "HR · hr.contract_expiry",
    "ev.document": "Истекает документ",
    "ev.documentD": "HR · hr.document_expiry",
    "ev.system": "Системные оповещения",
    "ev.systemD": "Ошибки синхронизации, фискальные ошибки, диск",
    "cfg.export": "Экспорт .env",
    "cfg.import": "Импорт .env",
    "cfg.exported": ".env экспортирован",
    "cfg.imported": "Настройки импортированы",
    "tests.passed": "пройдено"
  }
};
// --- Keys added for the wired panel (self-update, empty/edge states) ---
(function () {
  var extra = {
    en: {
      "upd.title": "Updates", "upd.version": "Installed version", "upd.server": "Update server",
      "upd.mode": "Build", "upd.installed": "Installed app", "upd.dev": "Running from source",
      "upd.check": "Check for updates", "upd.pending": "Update pending",
      "upd.pendingMsg": "A previous update did not confirm a clean start. If the app is misbehaving, roll back per desktop/UPDATES.md.",
      "ntf.empty": "No recipients yet — add a Telegram chat ID below.",
      "cfg.restart": "restart the server to apply", "tests.failed": "FAIL",
    },
    uz: {
      "upd.title": "Yangilanishlar", "upd.version": "O‘rnatilgan versiya", "upd.server": "Yangilanish serveri",
      "upd.mode": "Build", "upd.installed": "O‘rnatilgan ilova", "upd.dev": "Manbadan ishlamoqda",
      "upd.check": "Yangilanishni tekshirish", "upd.pending": "Yangilanish kutilmoqda",
      "upd.pendingMsg": "Avvalgi yangilanish toza ishga tushishni tasdiqlamadi. Ilova noto‘g‘ri ishlasa, desktop/UPDATES.md bo‘yicha orqaga qayting.",
      "ntf.empty": "Hozircha qabul qiluvchilar yo‘q — quyida Telegram chat ID qo‘shing.",
      "cfg.restart": "qo‘llash uchun serverni qayta ishga tushiring", "tests.failed": "XATO",
    },
    ru: {
      "upd.title": "Обновления", "upd.version": "Установленная версия", "upd.server": "Сервер обновлений",
      "upd.mode": "Сборка", "upd.installed": "Установленное приложение", "upd.dev": "Запуск из исходников",
      "upd.check": "Проверить обновления", "upd.pending": "Обновление ожидает",
      "upd.pendingMsg": "Предыдущее обновление не подтвердило корректный запуск. Если приложение работает неправильно, откатитесь по desktop/UPDATES.md.",
      "ntf.empty": "Пока нет получателей — добавьте Telegram chat ID ниже.",
      "cfg.restart": "перезапустите сервер, чтобы применить", "tests.failed": "СБОЙ",
    },
  };
  for (var l in extra) { window.I18N[l] = Object.assign(window.I18N[l] || {}, extra[l]); }
})();

// --- Updates page ---
(function () {
  var extra = {
    en: {
      "nav.updates": "Updates",
      "upd.sub": "Keep this terminal up to date — signed and automatic.",
      "upd.current": "This install",
      "upd.lastChecked": "Last checked", "upd.lastUpdated": "Last updated",
      "upd.availableV": "Available version", "upd.upToDate": "Up to date",
      "upd.never": "never", "upd.checking": "Checking…", "upd.checkNow": "Check now",
      "upd.installNow": "Install now", "upd.history": "Update history",
      "upd.noHistory": "No updates applied on this PC yet.",
      "upd.disabledMode": "Updates disabled", "upd.newAvailable": "A new version is available",
      "upd.auto": "Every launch checks automatically. You can also check now.",
    },
    uz: {
      "nav.updates": "Yangilanishlar",
      "upd.sub": "Ushbu terminalni dolzarb saqlang — imzolangan va avtomatik.",
      "upd.current": "Ushbu o‘rnatma",
      "upd.lastChecked": "Oxirgi tekshiruv", "upd.lastUpdated": "Oxirgi yangilanish",
      "upd.availableV": "Mavjud versiya", "upd.upToDate": "Eng so‘nggi",
      "upd.never": "hech qachon", "upd.checking": "Tekshirilmoqda…", "upd.checkNow": "Tekshirish",
      "upd.installNow": "O‘rnatish", "upd.history": "Yangilanishlar tarixi",
      "upd.noHistory": "Bu kompyuterda hali yangilanish bo‘lmagan.",
      "upd.disabledMode": "Yangilanishlar o‘chirilgan", "upd.newAvailable": "Yangi versiya mavjud",
      "upd.auto": "Har ishga tushganda avtomatik tekshiriladi. Hozir ham tekshirishingiz mumkin.",
    },
    ru: {
      "nav.updates": "Обновления",
      "upd.sub": "Держите терминал в актуальном состоянии — подписано и автоматически.",
      "upd.current": "Эта установка",
      "upd.lastChecked": "Последняя проверка", "upd.lastUpdated": "Последнее обновление",
      "upd.availableV": "Доступная версия", "upd.upToDate": "Актуально",
      "upd.never": "никогда", "upd.checking": "Проверка…", "upd.checkNow": "Проверить",
      "upd.installNow": "Установить", "upd.history": "История обновлений",
      "upd.noHistory": "На этом ПК обновлений ещё не было.",
      "upd.disabledMode": "Обновления отключены", "upd.newAvailable": "Доступна новая версия",
      "upd.auto": "При каждом запуске выполняется проверка. Можно проверить и сейчас.",
    },
  };
  for (var l in extra) { window.I18N[l] = Object.assign(window.I18N[l] || {}, extra[l]); }
})();

// --- Logs page + Notifications catalogue + real license plans ---
(function () {
  var extra = {
    en: {
      "common.on": "On", "common.off": "Off",
      "nav.logs": "Logs",
      "ntf.tokenSet": "Configured",
      "ntf.catalogT": "Message types",
      "ntf.catalogHint": "Every kind of message this install can send over Telegram, and the routing category each belongs to.",
      "ntf.catalogLoading": "Loading message catalogue…",
      "ntf.toCustomer": "to customer",
      "ntf.bk.order_paid": "Orders", "ntf.bk.daily": "Shifts & daily", "ntf.bk.contract": "Contracts", "ntf.bk.document": "Documents", "ntf.bk.system": "System",
      "ntf.fam.orders": "Order alerts",
      "ntf.fam.ordersD": "Sent to staff chats on each order event — new, ready, paid, cancelled.",
      "ntf.fam.shifts": "Shift & daily reports",
      "ntf.fam.shiftsD": "Shift start / end, the end-of-shift summary report, and cashier handover.",
      "ntf.fam.hr": "HR & document alerts",
      "ntf.fam.hrD": "Contract, probation and document-expiry reminders for staff.",
      "ntf.fam.system": "System & sync",
      "ntf.fam.systemD": "The catch-all bucket — background cloud-sync, fiscal and license alerts.",
      "ntf.fam.bot": "Customer bot replies",
      "ntf.fam.botD": "What the Telegram bot answers customers: menu, order, status, loyalty, login.",
      "lic.plansLoading": "Loading plans…",
      "lic.plansOffline": "offline catalogue",
      "lic.planRequested": "Plan change requested — pending approval",
      "log.title": "Logs",
      "log.sub": "What the backend has been doing — errors and warnings highlighted.",
      "log.srcApp": "All", "log.srcError": "Errors only",
      "log.live": "Live", "log.refresh": "Refresh",
      "log.all": "All", "log.errors": "Errors", "log.warnings": "Warnings", "log.info": "Info",
      "log.searchPh": "Search logs…",
      "log.noFile": "No log file yet. Logs are written while the backend runs in the installed app.",
      "log.noMatch": "No log lines match this filter.",
      "log.empty": "No log entries yet.",
      "log.showing": "Showing",
    },
    uz: {
      "common.on": "Yoniq", "common.off": "O‘chiq",
      "nav.logs": "Loglar",
      "ntf.tokenSet": "Sozlangan",
      "ntf.catalogT": "Xabar turlari",
      "ntf.catalogHint": "Ushbu o‘rnatma Telegram orqali yuborishi mumkin bo‘lgan barcha xabar turlari va ularning yo‘naltirish toifasi.",
      "ntf.catalogLoading": "Xabarlar ro‘yxati yuklanmoqda…",
      "ntf.toCustomer": "mijozga",
      "ntf.bk.order_paid": "Buyurtmalar", "ntf.bk.daily": "Smena va kunlik", "ntf.bk.contract": "Shartnomalar", "ntf.bk.document": "Hujjatlar", "ntf.bk.system": "Tizim",
      "ntf.fam.orders": "Buyurtma xabarlari",
      "ntf.fam.ordersD": "Har bir buyurtma hodisasida xodim chatlariga yuboriladi — yangi, tayyor, to‘langan, bekor.",
      "ntf.fam.shifts": "Smena va kunlik hisobotlar",
      "ntf.fam.shiftsD": "Smena boshlanishi / tugashi, smena yakuni hisoboti va kassir almashinuvi.",
      "ntf.fam.hr": "HR va hujjat ogohlantirishlari",
      "ntf.fam.hrD": "Xodimlar uchun shartnoma, sinov va hujjat muddati tugashi eslatmalari.",
      "ntf.fam.system": "Tizim va sinxronlash",
      "ntf.fam.systemD": "Umumiy toifa — fon bulutli sinxronlash, fiskal va litsenziya ogohlantirishlari.",
      "ntf.fam.bot": "Mijoz bot javoblari",
      "ntf.fam.botD": "Telegram bot mijozlarga nima javob beradi: menyu, buyurtma, holat, sodiqlik, kirish.",
      "lic.plansLoading": "Tariflar yuklanmoqda…",
      "lic.plansOffline": "oflayn ro‘yxat",
      "lic.planRequested": "Tarif o‘zgartirish so‘raldi — tasdiq kutilmoqda",
      "log.title": "Loglar",
      "log.sub": "Backend nima qilganini ko‘rsatadi — xato va ogohlantirishlar ajratilgan.",
      "log.srcApp": "Hammasi", "log.srcError": "Faqat xatolar",
      "log.live": "Jonli", "log.refresh": "Yangilash",
      "log.all": "Hammasi", "log.errors": "Xatolar", "log.warnings": "Ogohlantirishlar", "log.info": "Ma’lumot",
      "log.searchPh": "Loglardan qidirish…",
      "log.noFile": "Hali log fayli yo‘q. Loglar o‘rnatilgan ilovada backend ishlayotganda yoziladi.",
      "log.noMatch": "Bu filtrga mos log satrlari yo‘q.",
      "log.empty": "Hali log yozuvlari yo‘q.",
      "log.showing": "Ko‘rsatilmoqda",
    },
    ru: {
      "common.on": "Вкл", "common.off": "Выкл",
      "nav.logs": "Логи",
      "ntf.tokenSet": "Настроен",
      "ntf.catalogT": "Типы сообщений",
      "ntf.catalogHint": "Все типы сообщений, которые эта установка может отправлять через Telegram, и категория маршрутизации каждого.",
      "ntf.catalogLoading": "Загрузка каталога сообщений…",
      "ntf.toCustomer": "клиенту",
      "ntf.bk.order_paid": "Заказы", "ntf.bk.daily": "Смены и день", "ntf.bk.contract": "Договоры", "ntf.bk.document": "Документы", "ntf.bk.system": "Система",
      "ntf.fam.orders": "Оповещения о заказах",
      "ntf.fam.ordersD": "Отправляются в чаты персонала при каждом событии заказа — новый, готов, оплачен, отменён.",
      "ntf.fam.shifts": "Смены и дневные отчёты",
      "ntf.fam.shiftsD": "Начало / конец смены, итоговый отчёт смены и передача кассы.",
      "ntf.fam.hr": "HR и оповещения о документах",
      "ntf.fam.hrD": "Напоминания об истечении договоров, испытательного срока и документов сотрудников.",
      "ntf.fam.system": "Система и синхронизация",
      "ntf.fam.systemD": "Общая категория — фоновая облачная синхронизация, фискальные и лицензионные оповещения.",
      "ntf.fam.bot": "Ответы бота клиентам",
      "ntf.fam.botD": "Что бот Telegram отвечает клиентам: меню, заказ, статус, лояльность, вход.",
      "lic.plansLoading": "Загрузка тарифов…",
      "lic.plansOffline": "офлайн-каталог",
      "lic.planRequested": "Запрошена смена тарифа — ожидает подтверждения",
      "log.title": "Логи",
      "log.sub": "Чем занимался бэкенд — ошибки и предупреждения выделены.",
      "log.srcApp": "Все", "log.srcError": "Только ошибки",
      "log.live": "Live", "log.refresh": "Обновить",
      "log.all": "Все", "log.errors": "Ошибки", "log.warnings": "Предупреждения", "log.info": "Инфо",
      "log.searchPh": "Поиск по логам…",
      "log.noFile": "Файла логов пока нет. Логи пишутся, когда бэкенд работает в установленном приложении.",
      "log.noMatch": "Нет строк логов, соответствующих фильтру.",
      "log.empty": "Записей в логах пока нет.",
      "log.showing": "Показано",
    },
  };
  for (var l in extra) { window.I18N[l] = Object.assign(window.I18N[l] || {}, extra[l]); }
})();

window.tr = function (lang, key) {
  var d = window.I18N[lang] || window.I18N.en;
  return d[key] != null ? d[key] : (window.I18N.en[key] != null ? window.I18N.en[key] : key);
};

// --- Smooth updater progress window ---
(function () {
  var extra = {
    en: {
      "common.close": "Close",
      "upd.installing": "Installing…", "upd.secureUpdate": "SECURE UPDATE",
      "upd.modalTitle": "Installing your update", "upd.modalChecking": "Checking signatures…",
      "upd.modalPreparing": "Preparing the verified update…", "upd.modalRestarting": "Restarting Alpha POS",
      "upd.modalFailed": "Update could not finish", "upd.modalCurrent": "You’re up to date",
      "upd.signedVerified": "Cryptographically verified", "upd.tryAgain": "Try again",
      "upd.keepOpen": "You can keep this window open. Alpha POS will restart automatically."
    },
    uz: {
      "common.close": "Yopish",
      "upd.installing": "O‘rnatilmoqda…", "upd.secureUpdate": "XAVFSIZ YANGILANISH",
      "upd.modalTitle": "Yangilanish o‘rnatilmoqda", "upd.modalChecking": "Imzolar tekshirilmoqda…",
      "upd.modalPreparing": "Tasdiqlangan yangilanish tayyorlanmoqda…", "upd.modalRestarting": "Alpha POS qayta ishga tushmoqda",
      "upd.modalFailed": "Yangilanish tugallanmadi", "upd.modalCurrent": "Dastur dolzarb",
      "upd.signedVerified": "Kriptografik tasdiqlangan", "upd.tryAgain": "Qayta urinish",
      "upd.keepOpen": "Bu oynani ochiq qoldiring. Alpha POS avtomatik qayta ishga tushadi."
    },
    ru: {
      "common.close": "Закрыть",
      "upd.installing": "Установка…", "upd.secureUpdate": "БЕЗОПАСНОЕ ОБНОВЛЕНИЕ",
      "upd.modalTitle": "Установка обновления", "upd.modalChecking": "Проверка подписей…",
      "upd.modalPreparing": "Подготовка проверенного обновления…", "upd.modalRestarting": "Перезапуск Alpha POS",
      "upd.modalFailed": "Не удалось завершить обновление", "upd.modalCurrent": "Установлена последняя версия",
      "upd.signedVerified": "Криптографически проверено", "upd.tryAgain": "Повторить",
      "upd.keepOpen": "Оставьте это окно открытым. Alpha POS перезапустится автоматически."
    }
  };
  for (var l in extra) { window.I18N[l] = Object.assign(window.I18N[l] || {}, extra[l]); }
})();

/* source: app/ui.jsx */
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const AppCtx = React.createContext(null);
const useApp = () => React.useContext(AppCtx);
function Icon({
  name,
  size = 17
}) {
  const p = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round",
    strokeLinejoin: "round"
  };
  const paths = {
    dashboard: React.createElement("g", p, React.createElement("rect", {
      x: "3",
      y: "3",
      width: "7",
      height: "7",
      rx: "1.5"
    }), React.createElement("rect", {
      x: "14",
      y: "3",
      width: "7",
      height: "7",
      rx: "1.5"
    }), React.createElement("rect", {
      x: "3",
      y: "14",
      width: "7",
      height: "7",
      rx: "1.5"
    }), React.createElement("rect", {
      x: "14",
      y: "14",
      width: "7",
      height: "7",
      rx: "1.5"
    })),
    license: React.createElement("g", p, React.createElement("circle", {
      cx: "8.5",
      cy: "9",
      r: "4.5"
    }), React.createElement("path", {
      d: "M11.7 12.2 20 20.5M16 16.5l2-2M13.5 14l1.8-1.8"
    })),
    bell: React.createElement("g", p, React.createElement("path", {
      d: "M18 9a6 6 0 1 0-12 0c0 5-2 6-2 6h16s-2-1-2-6"
    }), React.createElement("path", {
      d: "M10.3 19a2 2 0 0 0 3.4 0"
    })),
    sliders: React.createElement("g", p, React.createElement("path", {
      d: "M4 7h10M18 7h2M4 12h2M10 12h10M4 17h10M18 17h2"
    }), React.createElement("circle", {
      cx: "16",
      cy: "7",
      r: "2"
    }), React.createElement("circle", {
      cx: "8",
      cy: "12",
      r: "2"
    }), React.createElement("circle", {
      cx: "16",
      cy: "17",
      r: "2"
    })),
    flask: React.createElement("g", p, React.createElement("path", {
      d: "M10 3v6L4.7 17.6A2 2 0 0 0 6.4 21h11.2a2 2 0 0 0 1.7-3.4L14 9V3"
    }), React.createElement("path", {
      d: "M8.5 3h7M7.5 14h9"
    })),
    receipt: React.createElement("g", p, React.createElement("path", {
      d: "M5 3h14v18l-2.3-1.5L14.4 21l-2.4-1.5L9.6 21l-2.3-1.5L5 21V3z"
    }), React.createElement("path", {
      d: "M9 8h6M9 12h6"
    })),
    power: React.createElement("g", _extends({}, p, {
      strokeWidth: "2"
    }), React.createElement("path", {
      d: "M12 3v8"
    }), React.createElement("path", {
      d: "M6.3 6.5a8 8 0 1 0 11.4 0"
    })),
    copy: React.createElement("g", p, React.createElement("rect", {
      x: "9",
      y: "9",
      width: "11",
      height: "11",
      rx: "2"
    }), React.createElement("path", {
      d: "M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"
    })),
    check: React.createElement("g", _extends({}, p, {
      strokeWidth: "2"
    }), React.createElement("path", {
      d: "M4.5 12.5 10 18 19.5 6.5"
    })),
    refresh: React.createElement("g", p, React.createElement("path", {
      d: "M20 11a8 8 0 0 0-15.3-2M4 13a8 8 0 0 0 15.3 2"
    }), React.createElement("path", {
      d: "M4 5v4h4M20 19v-4h-4"
    })),
    eye: React.createElement("g", p, React.createElement("path", {
      d: "M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"
    }), React.createElement("circle", {
      cx: "12",
      cy: "12",
      r: "2.8"
    })),
    send: React.createElement("g", p, React.createElement("path", {
      d: "M21 3 10.5 13.5M21 3l-7 18-3.5-7.5L3 10l18-7z"
    })),
    arrow: React.createElement("g", p, React.createElement("path", {
      d: "M5 12h14M13 6l6 6-6 6"
    })),
    warn: React.createElement("g", p, React.createElement("path", {
      d: "M12 3 2.5 20h19L12 3z"
    }), React.createElement("path", {
      d: "M12 10v4.5M12 17.5v.2"
    })),
    trash: React.createElement("g", p, React.createElement("path", {
      d: "M4 7h16M9 7V5a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 5v2M6.5 7l1 13h9l1-13"
    })),
    globe: React.createElement("g", p, React.createElement("circle", {
      cx: "12",
      cy: "12",
      r: "9"
    }), React.createElement("path", {
      d: "M3 12h18M12 3c2.7 2.6 4 5.8 4 9s-1.3 6.4-4 9c-2.7-2.6-4-5.8-4-9s1.3-6.4 4-9z"
    })),
    download: React.createElement("g", p, React.createElement("path", {
      d: "M12 3v11M7.5 10.5 12 15l4.5-4.5"
    }), React.createElement("path", {
      d: "M4 17v2.5A1.5 1.5 0 0 0 5.5 21h13a1.5 1.5 0 0 0 1.5-1.5V17"
    })),
    upload: React.createElement("g", p, React.createElement("path", {
      d: "M12 14V3M7.5 7.5 12 3l4.5 4.5"
    }), React.createElement("path", {
      d: "M4 17v2.5A1.5 1.5 0 0 0 5.5 21h13a1.5 1.5 0 0 0 1.5-1.5V17"
    })),
    heart: React.createElement("g", p, React.createElement("path", {
      d: "M3 12h4l2-5 3.5 10L15 9l1.5 3H21"
    })),
    logs: React.createElement("g", p, React.createElement("rect", {
      x: "4",
      y: "3",
      width: "16",
      height: "18",
      rx: "2"
    }), React.createElement("path", {
      d: "M8 8h8M8 12h8M8 16h5"
    })),
    search: React.createElement("g", p, React.createElement("circle", {
      cx: "11",
      cy: "11",
      r: "6.5"
    }), React.createElement("path", {
      d: "M16 16l4.5 4.5"
    })),
    close: React.createElement("g", p, React.createElement("path", {
      d: "M5 5l14 14M19 5L5 19"
    }))
  };
  return React.createElement("svg", {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    "aria-hidden": "true"
  }, paths[name] || null);
}
function Card({
  title,
  action,
  children,
  tone,
  style,
  label
}) {
  return React.createElement("section", {
    className: "card" + (tone ? " tone-" + tone : ""),
    style: style,
    "aria-label": label || title
  }, (title || action) && React.createElement("div", {
    className: "card-head"
  }, React.createElement("h3", {
    className: "card-t"
  }, title), action || null), children);
}
function KRow({
  l,
  v,
  mono,
  dim,
  badge
}) {
  return React.createElement("div", {
    className: "kv-row"
  }, React.createElement("span", {
    className: "kv-l"
  }, l), badge ? badge : React.createElement("span", {
    className: "kv-v" + (mono ? " mono" : "") + (dim ? " dim" : "")
  }, v));
}
function Badge({
  tone = "muted",
  children,
  pulse
}) {
  return React.createElement("span", {
    className: "badge " + tone
  }, React.createElement("i", {
    className: "dot" + (pulse ? " pulse" : "")
  }), children);
}
function Btn({
  variant = "ghost",
  size,
  icon,
  children,
  ...rest
}) {
  return React.createElement("button", _extends({
    className: "btn btn-" + variant + (size ? " btn-" + size : "")
  }, rest), icon ? React.createElement(Icon, {
    name: icon,
    size: 15
  }) : null, children);
}
function Field({
  l,
  hint,
  children,
  style
}) {
  return React.createElement("label", {
    className: "field",
    style: style
  }, l ? React.createElement("span", {
    className: "field-l"
  }, l) : null, children, hint ? React.createElement("span", {
    className: "field-hint"
  }, hint) : null);
}
function Seg({
  options,
  value,
  onChange
}) {
  return React.createElement("div", {
    className: "seg",
    role: "tablist"
  }, options.map(o => React.createElement("button", {
    key: o.v,
    className: o.v === value ? "active" : "",
    onClick: () => onChange(o.v),
    role: "tab",
    "aria-selected": o.v === value
  }, o.l)));
}
function Switch({
  on,
  onChange
}) {
  return React.createElement("button", {
    className: "switch" + (on ? " on" : ""),
    onClick: () => onChange(!on),
    role: "switch",
    "aria-checked": on
  });
}
function CopyBtn({
  text
}) {
  const [copied, setCopied] = React.useState(false);
  const app = useApp();
  return React.createElement("button", {
    className: "copy-btn" + (copied ? " copied" : ""),
    title: app.t("common.copy"),
    onClick: () => {
      try {
        navigator.clipboard && navigator.clipboard.writeText(text);
      } catch (e) {}
      setCopied(true);
      app.toast(app.t("common.copied"));
      setTimeout(() => setCopied(false), 1600);
    }
  }, React.createElement(Icon, {
    name: copied ? "check" : "copy",
    size: 14
  }));
}
function EpRow({
  l,
  v,
  copy
}) {
  return React.createElement("div", {
    className: "ep-row"
  }, React.createElement("span", {
    className: "ep-l"
  }, l), React.createElement("span", {
    className: "ep-v"
  }, v), copy !== false ? React.createElement(CopyBtn, {
    text: String(v)
  }) : null);
}
function ConfirmBtn({
  variant,
  icon,
  label,
  onConfirm
}) {
  const app = useApp();
  const [armed, setArmed] = React.useState(false);
  React.useEffect(() => {
    if (!armed) return;
    const id = setTimeout(() => setArmed(false), 3000);
    return () => clearTimeout(id);
  }, [armed]);
  return React.createElement(Btn, {
    variant: variant,
    icon: icon,
    onClick: () => {
      if (armed) {
        setArmed(false);
        onConfirm();
      } else setArmed(true);
    }
  }, armed ? app.t("common.confirm") : label);
}
Object.assign(window, {
  AppCtx,
  useApp,
  Icon,
  Card,
  KRow,
  Badge,
  Btn,
  Field,
  Seg,
  Switch,
  CopyBtn,
  EpRow,
  ConfirmBtn
});

/* source: app/screens-main.jsx */
function DashboardScreen() {
  const app = useApp();
  const {
    t,
    server,
    hb,
    lic,
    fiscal,
    updates,
    adminCreds
  } = app;
  const [showPwd, setShowPwd] = React.useState(false);
  const phase = server.phase;
  const statusTitle = phase === "on" ? t("dash.serverOn") : phase === "starting" ? t("dash.starting") : phase === "stopping" ? t("dash.stopping") : t("dash.serverOff");
  const statusSub = phase === "on" ? t("dash.serverOnSub") : phase === "off" ? t("dash.serverOffSub") : " ";
  return React.createElement("div", {
    className: "page",
    "data-screen-label": "Dashboard"
  }, React.createElement("header", {
    className: "page-head"
  }, React.createElement("h1", {
    className: "page-h"
  }, t("dash.title")), React.createElement("p", {
    className: "page-sub"
  }, t("dash.sub"))), React.createElement("div", {
    className: "g12"
  }, React.createElement(Card, {
    style: {
      gridColumn: "span 7",
      display: "flex",
      alignItems: "center"
    },
    label: "Server control"
  }, React.createElement("div", {
    className: "hero-wrap",
    style: {
      width: "100%"
    }
  }, React.createElement("button", {
    className: "power" + (phase === "on" ? " on" : "") + (phase === "starting" || phase === "stopping" ? " busy" : ""),
    onClick: server.toggle,
    disabled: phase === "starting" || phase === "stopping",
    "aria-label": phase === "on" ? "Stop server" : "Start server"
  }, React.createElement("span", {
    className: "power-ring"
  }), React.createElement(Icon, {
    name: "power",
    size: 34
  })), React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, React.createElement("div", {
    className: "hero-status"
  }, statusTitle), React.createElement("div", {
    className: "hero-sub"
  }, statusSub), server.error ? React.createElement("div", {
    style: {
      marginTop: 8,
      color: "var(--danger)",
      fontSize: 12.5,
      wordBreak: "break-word"
    }
  }, server.error) : null, React.createElement("div", {
    style: {
      marginTop: 14
    }
  }, React.createElement(EpRow, {
    l: t("dash.local"),
    v: "http://127.0.0.1:" + app.cfg.port
  }), React.createElement(EpRow, {
    l: t("dash.network"),
    v: "http://" + app.cfg.lanIp + ":" + app.cfg.port
  }), React.createElement("div", {
    className: "ep-row"
  }, React.createElement("span", {
    className: "ep-l"
  }, t("dash.uptime")), React.createElement("span", {
    className: "ep-v"
  }, phase === "on" ? server.uptimeStr : "—")))))), React.createElement(Card, {
    title: t("dash.heartbeat"),
    style: {
      gridColumn: "span 5"
    },
    action: React.createElement(Badge, {
      tone: hb.online ? "ok" : "muted",
      pulse: hb.online
    }, hb.online ? t("common.online") : t("common.offline"))
  }, React.createElement("div", {
    className: "kv"
  }, React.createElement(KRow, {
    l: t("dash.controlCenter"),
    v: app.cfg.controlHost,
    mono: true
  }), React.createElement(KRow, {
    l: t("dash.lastBeat"),
    v: hb.lastBeatStr,
    dim: !hb.hasBeat
  }), React.createElement(KRow, {
    l: t("dash.nextBeat"),
    v: hb.nextIn != null ? hb.nextIn + "s" : "—",
    dim: !hb.alive
  }), React.createElement(KRow, {
    l: t("dash.pending"),
    v: hb.pending
  }), React.createElement(KRow, {
    l: t("dash.lastError"),
    v: hb.lastError || t("common.none"),
    dim: !hb.lastError
  })), React.createElement("div", {
    style: {
      marginTop: 14
    }
  }, React.createElement(Btn, {
    variant: "ghost",
    size: "sm",
    icon: "refresh",
    onClick: hb.syncNow,
    disabled: !hb.canSync
  }, t("dash.syncNow")))), React.createElement(Card, {
    title: t("dash.license"),
    style: {
      gridColumn: "span 6"
    },
    action: React.createElement(Badge, {
      tone: lic.registered ? "ok" : "warn"
    }, lic.registered ? t("common.active") : t("common.unregistered"))
  }, lic.registered ? React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "auto 1fr",
      gap: "4px 36px",
      alignItems: "end"
    }
  }, React.createElement("div", null, React.createElement("div", {
    className: "kv-l",
    style: {
      color: "var(--ink-3)",
      fontSize: 13
    }
  }, t("dash.balance")), React.createElement("div", {
    className: "stat-big"
  }, lic.balance, React.createElement("span", {
    className: "unit"
  }, "UZS"))), React.createElement("div", {
    className: "kv"
  }, React.createElement(KRow, {
    l: t("dash.org"),
    v: lic.org
  }), React.createElement(KRow, {
    l: t("dash.plan"),
    v: lic.plan
  }), React.createElement(KRow, {
    l: t("dash.expires"),
    v: lic.expires,
    mono: true
  })), React.createElement("div", {
    style: {
      gridColumn: "1 / -1",
      marginTop: 14
    }
  }, React.createElement("div", {
    className: "meter"
  }, React.createElement("i", {
    style: {
      width: lic.pct + "%"
    }
  })), React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      marginTop: 6,
      fontSize: 12,
      color: "var(--ink-3)"
    }
  }, React.createElement("span", null, lic.daysLeft, " ", t("dash.daysLeft")), React.createElement("button", {
    onClick: () => app.nav("license"),
    style: {
      border: 0,
      background: "none",
      padding: 0,
      font: "inherit",
      fontSize: 12,
      fontWeight: 600,
      color: "var(--accent)",
      cursor: "pointer"
    }
  }, t("common.manage"), " \u2192")))) : React.createElement("div", null, React.createElement("div", {
    className: "kv"
  }, React.createElement(KRow, {
    l: t("dash.org"),
    v: "\u2014",
    dim: true
  }), React.createElement(KRow, {
    l: t("dash.balance"),
    v: "\u2014",
    dim: true
  }), React.createElement(KRow, {
    l: t("dash.expires"),
    v: "\u2014",
    dim: true
  })), React.createElement("div", {
    style: {
      marginTop: 14
    }
  }, React.createElement(Btn, {
    variant: "primary",
    size: "sm",
    icon: "arrow",
    onClick: () => app.nav("license")
  }, t("dash.registerNow"))))), React.createElement(Card, {
    title: t("dash.fiscal"),
    style: {
      gridColumn: "span 3"
    }
  }, React.createElement("div", {
    className: "kv"
  }, React.createElement(KRow, {
    l: t("dash.mode"),
    v: t("fis." + fiscal.mode)
  }), React.createElement(KRow, {
    l: t("dash.provider"),
    v: fiscal.provider,
    mono: true
  }), React.createElement(KRow, {
    l: t("dash.confirmedFailed"),
    v: fiscal.confirmed + " / " + fiscal.failed,
    mono: true
  })), React.createElement("div", {
    style: {
      marginTop: 14
    }
  }, React.createElement(Btn, {
    variant: "ghost",
    size: "sm",
    onClick: () => app.nav("fiscal")
  }, t("common.manage")))), React.createElement(Card, {
    title: t("dash.signin"),
    style: {
      gridColumn: "span 3"
    }
  }, React.createElement("div", {
    className: "kv"
  }, React.createElement(KRow, {
    l: t("dash.adminEmail"),
    v: adminCreds.email || "—",
    mono: true
  }), React.createElement(KRow, {
    l: t("dash.password"),
    v: adminCreds.password ? showPwd ? adminCreds.password : "••••••••" : "—",
    mono: true
  })), React.createElement("div", {
    className: "hstack",
    style: {
      marginTop: 14
    }
  }, React.createElement(Btn, {
    variant: "ghost",
    size: "sm",
    icon: "eye",
    onClick: () => setShowPwd(!showPwd),
    disabled: !adminCreds.password
  }, showPwd ? t("dash.hidePwd") : t("dash.showPwd")), adminCreds.password ? React.createElement(CopyBtn, {
    text: adminCreds.password
  }) : null)), React.createElement(Card, {
    title: t("upd.title"),
    style: {
      gridColumn: "span 12"
    },
    action: updates.pending ? React.createElement(Badge, {
      tone: "warn"
    }, t("upd.pending")) : React.createElement(Badge, {
      tone: "ok"
    }, "v", updates.version)
  }, React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      gap: 16,
      flexWrap: "wrap"
    }
  }, React.createElement("div", {
    className: "kv",
    style: {
      flex: 1,
      minWidth: 260
    }
  }, React.createElement(KRow, {
    l: t("upd.version"),
    v: "v" + updates.version,
    mono: true
  }), React.createElement(KRow, {
    l: t("upd.server"),
    v: updates.url || t("common.none"),
    mono: true,
    dim: !updates.url
  }), React.createElement(KRow, {
    l: t("upd.mode"),
    v: updates.frozen ? t("upd.installed") : t("upd.dev")
  })), React.createElement(Btn, {
    variant: "ghost",
    icon: "arrow",
    onClick: () => app.nav("updates")
  }, t("common.manage"))), updates.pending && React.createElement("p", {
    style: {
      margin: "12px 0 0",
      color: "var(--warn)",
      fontSize: 13
    }
  }, t("upd.pendingMsg")))));
}
const FALLBACK_PLANS = [{
  id: "starter",
  name: "Starter",
  descKey: "lic.p1d",
  price: null,
  currency: "UZS",
  period: "mo"
}, {
  id: "standard",
  name: "Standard",
  descKey: "lic.p2d",
  price: null,
  currency: "UZS",
  period: "mo"
}, {
  id: "pro",
  name: "Pro",
  descKey: "lic.p3d",
  price: null,
  currency: "UZS",
  period: "mo"
}];
function normalizePlans(data) {
  if (!data) return [];
  const arr = Array.isArray(data) ? data : Array.isArray(data.plans) ? data.plans : Array.isArray(data.results) ? data.results : Array.isArray(data.data) ? data.data : [];
  return arr.map((p, i) => {
    const id = p.id != null ? p.id : p.plan_id != null ? p.plan_id : p.code || p.slug || p.name || String(i);
    const name = p.name || p.title || p.label || p.display_name || String(id);
    const price = [p.price, p.price_uzs, p.monthly_price, p.amount].find(x => x != null);
    const desc = p.description || p.desc || p.summary || (Array.isArray(p.features) ? p.features.join(" · ") : "");
    return {
      id: String(id),
      name: String(name),
      price,
      currency: p.currency || "UZS",
      period: p.period || p.interval || p.billing_period || "mo",
      desc
    };
  });
}
function fmtPrice(v) {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : Number(String(v).replace(/[^\d.]/g, ""));
  if (!isFinite(n) || n <= 0) return String(v);
  return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}
function LicenseScreen() {
  const app = useApp();
  const {
    t,
    lic,
    hb
  } = app;
  const [plans, setPlans] = React.useState(null);
  const [plansFallback, setPlansFallback] = React.useState(false);
  const [sel, setSel] = React.useState(null);
  const [email, setEmail] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const curName = lic.registered ? String(lic.plan || "").trim().toLowerCase() : "";
  const current = (plans || []).find(p => p.name.toLowerCase() === curName || p.id.toLowerCase() === curName);
  React.useEffect(() => {
    let live = true;
    api.license_plans().then(r => {
      if (!live) return;
      const got = r && r.ok ? normalizePlans(r.data) : [];
      if (got.length) {
        setPlans(got);
        setPlansFallback(false);
      } else {
        setPlans(FALLBACK_PLANS.map(p => ({
          ...p,
          desc: ""
        })));
        setPlansFallback(true);
      }
    });
    return () => {
      live = false;
    };
  }, []);
  React.useEffect(() => {
    if (current) setSel(current.id);
  }, [current && current.id]);
  const apply = async () => {
    if (!sel || busy) return;
    setBusy(true);
    try {
      if (lic.registered) {
        const r = await api.license_plan_change(sel, "");
        app.toast(r && r.ok ? t("lic.planRequested") : r && r.data && r.data.message || r && r.error || t("lic.needsUrl"));
        app.refreshAll();
      } else {
        await app.activateLicense({
          email: email,
          plan: sel
        });
      }
    } finally {
      setBusy(false);
    }
  };
  const planDesc = p => p.descKey ? t(p.descKey) : p.desc || "";
  const applyDisabled = busy || !sel || (lic.registered ? current && sel === current.id : !email);
  return React.createElement("div", {
    className: "page",
    "data-screen-label": "License & Subscription"
  }, React.createElement("header", {
    className: "page-head"
  }, React.createElement("h1", {
    className: "page-h"
  }, t("lic.title")), React.createElement("p", {
    className: "page-sub"
  }, t("lic.sub"))), React.createElement("div", {
    className: "stack"
  }, React.createElement(Card, {
    title: t("lic.current"),
    action: React.createElement(Badge, {
      tone: lic.registered ? "ok" : "warn"
    }, lic.registered ? t("common.active") : t("common.unregistered"))
  }, lic.registered ? React.createElement("div", null, React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1.2fr 1fr 1.2fr",
      gap: 36,
      alignItems: "start"
    }
  }, React.createElement("div", null, React.createElement("div", {
    className: "kv-l",
    style: {
      fontSize: 13,
      color: "var(--ink-3)"
    }
  }, t("dash.org")), React.createElement("div", {
    className: "stat-big",
    style: {
      fontSize: 26
    }
  }, lic.org), React.createElement("div", {
    style: {
      color: "var(--ink-3)",
      fontSize: 13,
      marginTop: 4
    }
  }, lic.plan)), React.createElement("div", null, React.createElement("div", {
    className: "kv-l",
    style: {
      fontSize: 13,
      color: "var(--ink-3)"
    }
  }, t("dash.balance")), React.createElement("div", {
    className: "stat-big",
    style: {
      fontSize: 26
    }
  }, lic.balance, React.createElement("span", {
    className: "unit"
  }, "UZS"))), React.createElement("div", {
    className: "kv"
  }, React.createElement(KRow, {
    l: t("dash.expires"),
    v: lic.expires,
    mono: true
  }), React.createElement(KRow, {
    l: t("lic.heartbeat"),
    v: hb.hasBeat ? hb.lastBeatStr : "—",
    mono: hb.hasBeat,
    dim: !hb.hasBeat
  }))), React.createElement("div", {
    style: {
      marginTop: 20
    }
  }, React.createElement("div", {
    className: "meter"
  }, React.createElement("i", {
    style: {
      width: lic.pct + "%"
    }
  })), React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      marginTop: 6,
      fontSize: 12,
      color: "var(--ink-3)"
    }
  }, React.createElement("span", null, lic.daysLeft, " ", t("dash.daysLeft")), React.createElement("span", {
    className: "mono"
  }, lic.expires))), lic.warn && lic.lastMessage ? React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 7,
      margin: "14px 0 0",
      color: "var(--warn)",
      fontSize: 12.5
    }
  }, React.createElement(Icon, {
    name: "warn",
    size: 14
  }), React.createElement("span", {
    style: {
      textWrap: "pretty"
    }
  }, lic.lastMessage)) : null, React.createElement("div", {
    className: "hstack",
    style: {
      marginTop: 18
    }
  }, React.createElement(Btn, {
    variant: "ghost",
    size: "sm",
    icon: "refresh",
    onClick: hb.syncNow,
    disabled: !hb.canSync
  }, t("lic.syncNow")), React.createElement(ConfirmBtn, {
    variant: "danger",
    icon: "trash",
    label: t("lic.deactivate"),
    onConfirm: app.deactivateLicense
  }))) : React.createElement("div", {
    className: "g2",
    style: {
      alignItems: "end"
    }
  }, React.createElement(Field, {
    l: t("lic.email"),
    hint: t("lic.needsUrl")
  }, React.createElement("input", {
    className: "inp",
    placeholder: "you@business.uz",
    value: email,
    onChange: e => setEmail(e.target.value)
  })), React.createElement("div", {
    className: "kv"
  }, React.createElement(KRow, {
    l: t("dash.org"),
    v: "\u2014",
    dim: true
  }), React.createElement(KRow, {
    l: t("dash.balance"),
    v: "\u2014",
    dim: true
  })))), React.createElement(Card, {
    title: t("lic.plansT"),
    action: plansFallback ? React.createElement(Badge, {
      tone: "muted"
    }, t("lic.plansOffline")) : null
  }, React.createElement("p", {
    style: {
      margin: "0 0 14px",
      color: "var(--ink-3)",
      fontSize: 13
    }
  }, t("lic.plansHint")), plans === null ? React.createElement("p", {
    style: {
      color: "var(--ink-3)",
      fontSize: 13,
      margin: "2px 0"
    }
  }, t("lic.plansLoading")) : React.createElement("div", {
    className: "plan-grid"
  }, plans.map(p => {
    const isCur = current && p.id === current.id;
    const price = fmtPrice(p.price);
    return React.createElement("button", {
      key: p.id,
      className: "plan" + (sel === p.id ? " sel" : ""),
      onClick: () => setSel(p.id)
    }, isCur && React.createElement("span", {
      className: "pl-badge"
    }, React.createElement(Badge, {
      tone: "ok"
    }, t("lic.currentPlan"))), React.createElement("div", {
      className: "pl-name"
    }, p.name), React.createElement("div", {
      className: "pl-desc"
    }, planDesc(p)), React.createElement("div", {
      className: "pl-price"
    }, price ? React.createElement(React.Fragment, null, price, " ", p.currency, " ", React.createElement("span", {
      className: "mo"
    }, "/ " + (p.period || t("lic.mo").replace(/^\/\s*/, "")))) : React.createElement("span", {
      style: {
        color: "var(--ink-3)",
        fontWeight: 400
      }
    }, "\u2014")));
  })), React.createElement("div", {
    style: {
      marginTop: 18
    }
  }, React.createElement(Btn, {
    variant: "primary",
    icon: "arrow",
    disabled: applyDisabled,
    onClick: apply
  }, busy ? t("common.running") : lic.registered ? t("lic.switch") : t("lic.registerBtn"))))));
}
Object.assign(window, {
  DashboardScreen,
  LicenseScreen
});

/* source: app/screens-admin.jsx */
function EventRow({
  k,
  on,
  onToggle
}) {
  const app = useApp();
  return React.createElement("div", {
    className: "ev-row"
  }, React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, React.createElement("div", {
    className: "ev-name"
  }, app.t("ev." + k)), React.createElement("div", {
    className: "ev-desc"
  }, app.t("ev." + k + "D"))), React.createElement(Switch, {
    on: on,
    onChange: onToggle
  }));
}
function NotifCatalog() {
  const app = useApp();
  const {
    t
  } = app;
  const [cat, setCat] = React.useState(null);
  React.useEffect(() => {
    api.notif_catalog().then(r => {
      if (r && r.ok) setCat(r);
    });
  }, []);
  if (cat === null) {
    return React.createElement(Card, {
      title: t("ntf.catalogT")
    }, React.createElement("p", {
      style: {
        color: "var(--ink-3)",
        fontSize: 13,
        margin: "2px 0"
      }
    }, t("ntf.catalogLoading")));
  }
  const groups = (cat.groups || []).filter(g => (g.items || []).length || g.key === "system");
  return React.createElement(Card, {
    title: t("ntf.catalogT")
  }, React.createElement("p", {
    style: {
      margin: "0 0 6px",
      color: "var(--ink-3)",
      fontSize: 13,
      textWrap: "pretty"
    }
  }, t("ntf.catalogHint")), React.createElement("div", {
    className: "msg-cat"
  }, groups.map(g => React.createElement("div", {
    key: g.key,
    className: "msg-fam"
  }, React.createElement("div", {
    className: "msg-fam-head"
  }, React.createElement("span", {
    className: "msg-fam-name"
  }, t("ntf.fam." + g.key)), React.createElement("span", {
    className: "msg-fam-desc"
  }, t("ntf.fam." + g.key + "D"))), (g.items || []).length ? React.createElement("div", {
    className: "msg-list"
  }, g.items.map(it => React.createElement("div", {
    key: it.type,
    className: "msg-item",
    title: it.type
  }, React.createElement("span", {
    className: "msg-state" + (it.enabled ? " on" : "")
  }, it.enabled ? t("common.on") : t("common.off")), React.createElement("span", {
    className: "msg-name"
  }, it.name), React.createElement("span", {
    className: "msg-type mono"
  }, it.type), React.createElement("span", {
    className: "msg-bucket"
  }, g.key === "bot" ? t("ntf.toCustomer") : t("ntf.bk." + it.bucket))))) : null))));
}
function NotificationsScreen() {
  const app = useApp();
  const {
    t
  } = app;
  const [types, setTypes] = React.useState(["order_paid", "daily", "contract", "document", "system"]);
  const [recipients, setRecipients] = React.useState([]);
  const [selId, setSelId] = React.useState(null);
  const [newId, setNewId] = React.useState("");
  const [brand, setBrand] = React.useState("Alpha POS");
  const [token, setToken] = React.useState("");
  const [botSet, setBotSet] = React.useState(false);
  const [enabled, setEnabled] = React.useState(true);
  const loaded = React.useRef(false);
  React.useEffect(() => {
    api.notif_settings().then(r => {
      if (r && r.ok) {
        setBrand(r.brand_name || "Alpha POS");
        setBotSet(!!r.bot_token_set);
        setEnabled(r.is_enabled !== false);
      }
    });
    api.notif_routing().then(r => {
      if (r && r.ok) {
        setTypes(r.types || types);
        setRecipients(r.recipients || []);
        if (r.recipients && r.recipients.length) setSelId(r.recipients[0].cid);
      }
      loaded.current = true;
    });
  }, []);
  const persist = list => {
    if (loaded.current) api.set_notif_routing(list);
  };
  const commit = list => {
    setRecipients(list);
    persist(list);
  };
  const sel = recipients.find(r => r.cid === selId) || recipients[0];
  const update = (cid, fn) => commit(recipients.map(r => r.cid === cid ? fn(r) : r));
  const addRecipient = () => {
    const cid = newId.replace(/\D/g, "");
    if (!cid || recipients.some(r => r.cid === cid)) return;
    const ev = {};
    types.forEach(tp => ev[tp] = true);
    const list = [...recipients, {
      cid,
      label: "Chat " + cid.slice(-4),
      events: ev
    }];
    commit(list);
    setSelId(cid);
    setNewId("");
    app.toast(t("ntf.added"));
  };
  const removeRecipient = cid => {
    const next = recipients.filter(r => r.cid !== cid);
    if (next.length && cid === selId) setSelId(next[0].cid);
    commit(next);
    app.toast(t("ntf.removed"));
  };
  const saveBot = () => {
    api.save_notif_settings(token || null, null, brand).then(r => {
      if (r && r.ok) {
        app.toast(t("common.saved"));
        setToken("");
        setBotSet(botSet || !!token);
      } else app.toast(r && r.error || "Save failed");
    });
  };
  const toggleEnabled = on => {
    setEnabled(on);
    api.set_notif_enabled(on).then(r => {
      if (!(r && r.ok)) {
        setEnabled(!on);
        app.toast(r && r.error || "Failed");
        return;
      }
      app.toast(on ? t("common.on") : t("common.off"));
    });
  };
  return React.createElement("div", {
    className: "page",
    "data-screen-label": "Notifications"
  }, React.createElement("header", {
    className: "page-head"
  }, React.createElement("h1", {
    className: "page-h"
  }, t("ntf.title")), React.createElement("p", {
    className: "page-sub"
  }, t("ntf.sub"))), React.createElement("div", {
    className: "stack"
  }, React.createElement(Card, {
    title: t("ntf.telegram"),
    action: React.createElement(Badge, {
      tone: botSet ? "ok" : "muted"
    }, botSet ? t("ntf.tokenSet") : t("common.no"))
  }, React.createElement("div", {
    className: "hstack",
    style: {
      justifyContent: "space-between",
      alignItems: "center",
      marginBottom: 16
    }
  }, React.createElement("div", null, React.createElement("div", {
    style: {
      fontWeight: 600,
      fontSize: 14
    }
  }, t("ntf.enable")), React.createElement("div", {
    style: {
      fontSize: 12,
      color: "var(--ink-3)",
      marginTop: 2
    }
  }, t("ntf.enableHint"))), React.createElement(Switch, {
    on: enabled,
    onChange: toggleEnabled
  })), React.createElement("div", {
    className: "g2"
  }, React.createElement(Field, {
    l: t("ntf.botToken"),
    hint: t("ntf.botTokenHint")
  }, React.createElement("input", {
    className: "inp mono",
    type: "password",
    placeholder: botSet ? "•••••••• (set — blank keeps it)" : "paste bot token",
    value: token,
    onChange: e => setToken(e.target.value)
  })), React.createElement(Field, {
    l: t("ntf.brand")
  }, React.createElement("input", {
    className: "inp",
    value: brand,
    onChange: e => setBrand(e.target.value)
  }))), React.createElement("div", {
    className: "hstack",
    style: {
      marginTop: 16
    }
  }, React.createElement(Btn, {
    variant: "primary",
    onClick: saveBot
  }, t("ntf.saveTg")), React.createElement(Btn, {
    variant: "ghost",
    icon: "send",
    onClick: () => api.telegram_test().then(r => app.toast(r && r.ok ? t("ntf.testSent") : r && r.error || "Failed"))
  }, t("ntf.sendTest")))), React.createElement(Card, {
    title: t("ntf.recipients")
  }, recipients.length === 0 ? React.createElement("p", {
    style: {
      color: "var(--ink-3)",
      fontSize: 13,
      margin: "4px 0 14px"
    }
  }, t("ntf.empty")) : null, React.createElement("div", {
    className: "md"
  }, React.createElement("div", null, React.createElement("div", {
    className: "rcp-list"
  }, recipients.map(r => {
    const n = Object.values(r.events || {}).filter(Boolean).length;
    return React.createElement("button", {
      key: r.cid,
      className: "rcp" + (r.cid === selId ? " sel" : ""),
      onClick: () => setSelId(r.cid)
    }, React.createElement("span", {
      className: "rc-ava"
    }, ((r.label || "#")[0] || "#").toUpperCase()), React.createElement("span", {
      style: {
        minWidth: 0
      }
    }, React.createElement("span", {
      className: "rc-name",
      style: {
        display: "block"
      }
    }, r.label || "Chat " + r.cid.slice(-4)), React.createElement("span", {
      className: "rc-id"
    }, r.cid)), React.createElement("span", {
      className: "rc-count"
    }, n, "/", types.length));
  })), React.createElement("div", {
    className: "hstack",
    style: {
      marginTop: 12
    }
  }, React.createElement("input", {
    className: "inp mono",
    placeholder: t("ntf.addPh"),
    value: newId,
    onChange: e => setNewId(e.target.value),
    onKeyDown: e => e.key === "Enter" && addRecipient(),
    style: {
      flex: 1
    }
  }), React.createElement(Btn, {
    variant: "ghost",
    onClick: addRecipient,
    disabled: !newId.trim()
  }, t("ntf.addChat")))), sel && React.createElement("div", {
    style: {
      borderLeft: "1px solid var(--line)",
      paddingLeft: 20,
      minWidth: 0
    }
  }, React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "flex-end",
      gap: 14,
      flexWrap: "wrap"
    }
  }, React.createElement(Field, {
    l: t("ntf.labelL"),
    style: {
      flex: 1,
      minWidth: 160
    }
  }, React.createElement("input", {
    className: "inp",
    value: sel.label || "",
    onChange: e => update(sel.cid, r => ({
      ...r,
      label: e.target.value
    }))
  })), React.createElement(Field, {
    l: t("ntf.chatId"),
    style: {
      width: 170
    }
  }, React.createElement("div", {
    className: "hstack",
    style: {
      gap: 6
    }
  }, React.createElement("input", {
    className: "inp mono",
    value: sel.cid,
    readOnly: true,
    style: {
      flex: 1
    }
  }), React.createElement(CopyBtn, {
    text: sel.cid
  }))), React.createElement(ConfirmBtn, {
    variant: "danger",
    icon: "trash",
    label: t("ntf.removeChat"),
    onConfirm: () => removeRecipient(sel.cid)
  })), React.createElement("div", {
    className: "sec-l",
    style: {
      marginTop: 20
    }
  }, t("ntf.receives")), React.createElement("div", null, types.map(k => React.createElement(EventRow, {
    key: k + sel.cid,
    k: k,
    on: !!(sel.events || {})[k],
    onToggle: v => update(sel.cid, r => ({
      ...r,
      events: {
        ...r.events,
        [k]: v
      }
    }))
  }))), React.createElement("div", {
    style: {
      marginTop: 16
    }
  }, React.createElement(Btn, {
    variant: "ghost",
    icon: "send",
    onClick: () => api.send_test_to_chat(sel.cid).then(r => app.toast(r && r.ok ? t("ntf.testSent") + " → " + (sel.label || sel.cid) : r && r.error || "Failed"))
  }, t("ntf.sendThis")))))), React.createElement(NotifCatalog, null)));
}
const CFG_SECTIONS = [{
  t: "cfg.general",
  fields: [["BRANCH_ID", "text"], ["DEPLOYMENT_MODE", ["local", "cloud"]], ["PORT", "text"]]
}, {
  t: "cfg.sync",
  fields: [["CLOUD_SYNC_URL", "text"], ["SYNC_ENABLED", ["True", "False"]], ["CLOUD_SYNC_TOKEN", "secret"]]
}, {
  t: "cfg.licensing",
  fields: [["LICENSE_CONTROL_CENTER_URL", "text"], ["ALPHA_POS_UPDATE_URL", "text"]]
}, {
  t: "cfg.telegram",
  fields: [["TELEGRAM_WEBHOOK_SECRET", "secret"]]
}, {
  t: "cfg.ai",
  fields: [["AI_PROVIDER", ["claude", "gemini"]], ["ANTHROPIC_API_KEY", "secret"], ["ANTHROPIC_MODEL", "text"], ["GEMINI_API_KEY", "secret"], ["GEMINI_MODEL", "text"]]
}, {
  t: "cfg.fiscal",
  hint: "cfg.fiscalHint",
  fields: [["FISCALIZATION_MODE", ["off", "mock", "sandbox", "live"]], ["FISCAL_PROVIDER", ["mock", "multikassa"]], ["FISCAL_TIN", "text"], ["FISCAL_PROVIDER_URL", "text"], ["FISCAL_VAT_PERCENT", "text"], ["FISCAL_MERCHANT_ID", "text"], ["FISCAL_SECRET", "secret"]]
}];
function parseEnv(text) {
  const out = {};
  (text || "").split(/\r?\n/).forEach(line => {
    const s = line.trim();
    if (!s || s[0] === "#" || s.indexOf("=") < 0) return;
    const i = s.indexOf("=");
    out[s.slice(0, i).trim()] = s.slice(i + 1).trim();
  });
  return out;
}
function ConfigScreen() {
  const app = useApp();
  const {
    t
  } = app;
  const [vals, setVals] = React.useState({});
  const [secrets, setSecrets] = React.useState([]);
  const fileRef = React.useRef(null);
  const load = React.useCallback(() => {
    api.get_config().then(r => {
      if (r && r.ok) {
        setVals(r.config || {});
        setSecrets(r.secret_keys || []);
      }
    });
  }, []);
  React.useEffect(() => {
    load();
  }, [load]);
  const set = (k, v) => setVals(o => ({
    ...o,
    [k]: v
  }));
  const isSecret = k => secrets.indexOf(k) >= 0;
  const save = () => api.save_config(vals).then(r => app.toast(r && r.ok ? t("cfg.savedToast") + (r.restart_required ? " · " + t("cfg.restart") : "") : r && r.error || "Failed"));
  const exportEnv = async () => {
    const r = await api.export_config();
    if (!r || !r.ok) {
      app.toast("Export failed");
      return;
    }
    const lines = ["# Alpha POS — exported configuration"];
    Object.keys(r.config).sort().forEach(k => lines.push(k + "=" + (r.config[k] == null ? "" : r.config[k])));
    try {
      const blob = new Blob([lines.join("\n") + "\n"], {
        type: "text/plain"
      });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = r.filename || "alpha-pos.env";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    } catch (e) {}
    app.toast(t("cfg.exported"));
  };
  const onImportFile = e => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const obj = parseEnv(String(reader.result || ""));
      api.import_config(obj).then(r => {
        if (r && r.ok) {
          app.toast(t("cfg.imported"));
          load();
        } else app.toast(r && r.error || "Import failed");
      });
    };
    reader.readAsText(file);
    e.target.value = "";
  };
  const renderField = (key, type) => {
    if (Array.isArray(type)) {
      return React.createElement(Field, {
        l: key,
        key: key
      }, React.createElement("select", {
        className: "inp",
        value: vals[key] != null ? vals[key] : type[0],
        onChange: e => set(key, e.target.value)
      }, type.map(o => React.createElement("option", {
        key: o,
        value: o
      }, o))));
    }
    const secret = type === "secret" || isSecret(key);
    return React.createElement(Field, {
      l: key,
      key: key
    }, React.createElement("input", {
      className: "inp mono",
      type: secret ? "password" : "text",
      value: vals[key] != null ? vals[key] : "",
      placeholder: secret ? "•••••••• (blank keeps it)" : "",
      onChange: e => set(key, e.target.value)
    }));
  };
  return React.createElement("div", {
    className: "page",
    "data-screen-label": "Configuration"
  }, React.createElement("header", {
    className: "page-head",
    style: {
      display: "flex",
      alignItems: "flex-end",
      justifyContent: "space-between",
      gap: 16,
      flexWrap: "wrap"
    }
  }, React.createElement("div", null, React.createElement("h1", {
    className: "page-h"
  }, t("cfg.title")), React.createElement("p", {
    className: "page-sub"
  }, t("cfg.sub"))), React.createElement("div", {
    className: "hstack"
  }, React.createElement("input", {
    type: "file",
    accept: ".env,text/plain",
    ref: fileRef,
    style: {
      display: "none"
    },
    onChange: onImportFile
  }), React.createElement(Btn, {
    variant: "ghost",
    icon: "upload",
    onClick: () => fileRef.current && fileRef.current.click()
  }, t("cfg.import")), React.createElement(Btn, {
    variant: "ghost",
    icon: "download",
    onClick: exportEnv
  }, t("cfg.export")), React.createElement(Btn, {
    variant: "primary",
    onClick: save
  }, t("cfg.saveBtn")))), React.createElement("div", {
    className: "cfg-grid"
  }, CFG_SECTIONS.map(sec => React.createElement(Card, {
    title: t(sec.t),
    key: sec.t
  }, sec.hint ? React.createElement("p", {
    style: {
      margin: "0 0 14px",
      color: "var(--ink-3)",
      fontSize: 12.5
    }
  }, t(sec.hint)) : null, React.createElement("div", {
    className: sec.fields.length > 1 ? "g2" : "stack",
    style: {
      gap: 14
    }
  }, sec.fields.map(([k, ty]) => renderField(k, ty))))), React.createElement(Card, {
    title: t("cfg.flushT"),
    tone: "warn"
  }, React.createElement("p", {
    style: {
      margin: "0 0 16px",
      color: "var(--ink-2)",
      fontSize: 13,
      textWrap: "pretty"
    }
  }, t("cfg.flushD")), React.createElement(ConfirmBtn, {
    variant: "warn",
    icon: "refresh",
    label: t("cfg.flushBtn"),
    onConfirm: () => api.flush_database(true).then(r => app.toast(r && r.ok ? t("cfg.flushed") : r && r.error || "Failed"))
  })), React.createElement(Card, {
    title: t("cfg.dangerT"),
    tone: "danger"
  }, React.createElement("p", {
    style: {
      margin: "0 0 16px",
      color: "var(--ink-2)",
      fontSize: 13,
      textWrap: "pretty"
    }
  }, t("cfg.dangerD")), React.createElement(ConfirmBtn, {
    variant: "danger",
    icon: "trash",
    label: t("cfg.dangerBtn"),
    onConfirm: () => api.factory_reset(true).then(r => app.toast(r && r.ok ? r.message || "Done" : r && r.error || "Failed"))
  }))));
}
Object.assign(window, {
  NotificationsScreen,
  ConfigScreen
});

/* source: app/screens-ops.jsx */
const LOCAL_TESTS = [{
  name: "tests.t1",
  icon: "power",
  method: "test_server_connection"
}, {
  name: "tests.t2",
  icon: "arrow",
  method: "send_mock_sync"
}, {
  name: "tests.t3",
  icon: "copy",
  method: "fetch_mock_sync"
}, {
  name: "tests.t4",
  icon: "send",
  method: "telegram_test"
}, {
  name: "tests.t5",
  icon: "bell",
  method: "send_fake_notification"
}, {
  name: "tests.t6",
  icon: "receipt",
  method: "fiscal_test"
}];
const CLOUD_TESTS = [{
  name: "tests.t7",
  icon: "globe",
  method: "cloud_test_connection"
}, {
  name: "tests.t8",
  icon: "refresh",
  method: "cloud_sync_now"
}, {
  name: "tests.t9",
  icon: "flask",
  method: "cloud_pull"
}];
function TestTile({
  test,
  state,
  onRun
}) {
  const app = useApp();
  const running = state === "running";
  const done = state && state !== "running";
  const ok = done && state.ok;
  return React.createElement("div", {
    className: "tile" + (done && ok ? " pass" : "") + (done && !ok ? " fail" : "")
  }, React.createElement("span", {
    className: "ti-ico"
  }, React.createElement(Icon, {
    name: test.icon,
    size: 17
  })), React.createElement("div", {
    className: "ti-name"
  }, app.t(test.name)), React.createElement("div", {
    className: "ti-desc"
  }, app.t(test.name + "d")), React.createElement("div", {
    className: "ti-foot"
  }, React.createElement("span", {
    className: "ti-res"
  }, running && React.createElement("span", {
    className: "spinner"
  }), done && React.createElement(React.Fragment, null, React.createElement(Icon, {
    name: ok ? "check" : "warn",
    size: 13
  }), ok ? "OK" : app.t("tests.failed") || "FAIL", " \xB7 ", state.ms, " ms")), React.createElement(Btn, {
    variant: "ghost",
    size: "sm",
    onClick: onRun,
    disabled: running
  }, app.t("common.run"))));
}
function RecoveryPanel() {
  const app = useApp();
  const {
    t
  } = app;
  const [stuck, setStuck] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const refresh = React.useCallback(() => {
    api.cloud_dead_letters().then(r => {
      if (r && r.ok) setStuck({
        total: r.total || 0,
        by_model: r.by_model || {}
      });
    });
  }, []);
  React.useEffect(() => {
    refresh();
  }, [refresh]);
  const retry = () => {
    setBusy(true);
    api.cloud_resync_failed().then(r => {
      setBusy(false);
      const n = r && r.requeued || 0;
      app.toast(t("tests.retryDone").replace("{n}", n));
      refresh();
    });
  };
  const total = stuck ? stuck.total : null;
  const models = stuck ? Object.keys(stuck.by_model) : [];
  return React.createElement(Card, {
    title: t("tests.recovery"),
    tone: total > 0 ? "warn" : undefined,
    style: {
      marginTop: 28
    }
  }, React.createElement("p", {
    style: {
      margin: "0 0 14px",
      color: "var(--ink-3)",
      fontSize: 13,
      maxWidth: "80ch",
      textWrap: "pretty"
    }
  }, t("tests.recoveryHint")), React.createElement("div", {
    className: "kv"
  }, React.createElement(KRow, {
    l: t("tests.stuckLabel"),
    badge: React.createElement(Badge, {
      tone: total > 0 ? "warn" : "ok"
    }, total == null ? "…" : total)
  }), models.map(m => React.createElement(KRow, {
    key: m,
    l: m,
    v: String(stuck.by_model[m]),
    mono: true,
    dim: true
  }))), React.createElement("div", {
    style: {
      marginTop: 14,
      display: "flex",
      alignItems: "center",
      gap: 12,
      flexWrap: "wrap"
    }
  }, total === 0 && React.createElement("span", {
    style: {
      fontSize: 12.5,
      color: "var(--ok)"
    }
  }, t("tests.stuckNone")), total > 0 && React.createElement("span", {
    style: {
      fontSize: 12.5,
      color: "var(--ink-3)"
    }
  }, t("tests.stuckSome")), React.createElement(Btn, {
    variant: total > 0 ? "primary" : "ghost",
    icon: "refresh",
    onClick: retry,
    disabled: busy || !total
  }, busy ? t("common.running") : t("tests.retryStuck"))));
}
function TestsScreen() {
  const app = useApp();
  const {
    t
  } = app;
  const [results, setResults] = React.useState({});
  const all = [...LOCAL_TESTS, ...CLOUD_TESTS];
  const run = tt => {
    setResults(r => ({
      ...r,
      [tt.name]: "running"
    }));
    const start = window.performance && performance.now ? performance.now() : Date.now();
    api[tt.method]().then(res => {
      const ms = Math.round((window.performance && performance.now ? performance.now() : Date.now()) - start);
      const ok = !!(res && res.ok !== false);
      setResults(r => ({
        ...r,
        [tt.name]: {
          ok,
          ms
        }
      }));
    });
  };
  const runAll = () => all.forEach((tt, i) => setTimeout(() => run(tt), i * 250));
  const passedCount = all.filter(tt => {
    const s = results[tt.name];
    return s && s !== "running" && s.ok;
  }).length;
  return React.createElement("div", {
    className: "page",
    "data-screen-label": "Tests"
  }, React.createElement("header", {
    className: "page-head",
    style: {
      display: "flex",
      alignItems: "flex-end",
      justifyContent: "space-between",
      gap: 16
    }
  }, React.createElement("div", null, React.createElement("h1", {
    className: "page-h"
  }, t("tests.title")), React.createElement("p", {
    className: "page-sub"
  }, t("tests.sub"))), React.createElement("div", {
    className: "hstack"
  }, passedCount > 0 && React.createElement("span", {
    className: "mono",
    style: {
      fontSize: 12.5,
      color: "var(--ok)"
    }
  }, passedCount, " / ", all.length, " ", t("tests.passed")), React.createElement(Btn, {
    variant: "primary",
    icon: "flask",
    onClick: runAll
  }, t("common.runAll")))), React.createElement("div", {
    className: "sec-l"
  }, t("tests.local")), React.createElement("div", {
    className: "tile-grid"
  }, LOCAL_TESTS.map(tt => React.createElement(TestTile, {
    key: tt.name,
    test: tt,
    state: results[tt.name],
    onRun: () => run(tt)
  }))), React.createElement("div", {
    className: "sec-l",
    style: {
      marginTop: 28
    }
  }, t("tests.cloud")), React.createElement("p", {
    style: {
      margin: "0 0 12px",
      color: "var(--ink-3)",
      fontSize: 13,
      maxWidth: "78ch",
      textWrap: "pretty"
    }
  }, t("tests.cloudHint")), React.createElement("div", {
    className: "tile-grid"
  }, CLOUD_TESTS.map(tt => React.createElement(TestTile, {
    key: tt.name,
    test: tt,
    state: results[tt.name],
    onRun: () => run(tt)
  }))), React.createElement(RecoveryPanel, null));
}
function FiscalScreen() {
  const app = useApp();
  const {
    t,
    fiscal
  } = app;
  const [testing, setTesting] = React.useState(false);
  const runTest = () => {
    setTesting(true);
    api.fiscal_test().then(r => {
      setTesting(false);
      fiscal.bumpConfirmed();
      app.toast(r && r.ok ? t("fis.testOk") : r && r.error || "Failed");
    });
  };
  const yn = v => React.createElement(Badge, {
    tone: v ? "ok" : "muted"
  }, v ? t("common.yes") : t("common.no"));
  return React.createElement("div", {
    className: "page",
    "data-screen-label": "Fiscalization"
  }, React.createElement("header", {
    className: "page-head"
  }, React.createElement("h1", {
    className: "page-h"
  }, t("fis.title"), " ", React.createElement("span", {
    style: {
      color: "var(--ink-3)"
    }
  }, "\xB7 Soliq")), React.createElement("p", {
    className: "page-sub"
  }, t("fis.sub"))), React.createElement("div", {
    className: "g12"
  }, React.createElement(Card, {
    title: t("fis.mode"),
    style: {
      gridColumn: "span 6"
    }
  }, React.createElement(Seg, {
    value: fiscal.mode,
    onChange: fiscal.setMode,
    options: [{
      v: "off",
      l: t("fis.off")
    }, {
      v: "mock",
      l: t("fis.mock")
    }, {
      v: "sandbox",
      l: t("fis.sandbox")
    }, {
      v: "live",
      l: t("fis.live")
    }]
  }), React.createElement("div", {
    style: {
      marginTop: 18
    }
  }, React.createElement(Btn, {
    variant: "primary",
    icon: "receipt",
    onClick: runTest,
    disabled: testing
  }, testing ? t("common.running") : t("fis.runTest")))), React.createElement(Card, {
    title: t("fis.status"),
    style: {
      gridColumn: "span 6"
    }
  }, React.createElement("div", {
    className: "kv"
  }, React.createElement(KRow, {
    l: t("fis.enabled"),
    badge: yn(fiscal.mode !== "off")
  }), React.createElement(KRow, {
    l: t("fis.provider"),
    v: fiscal.provider,
    mono: true
  }), React.createElement(KRow, {
    l: t("fis.cf"),
    v: fiscal.confirmed + " / " + fiscal.failed,
    mono: true
  })))));
}
Object.assign(window, {
  TestsScreen,
  FiscalScreen
});

/* source: app/screens-updates.jsx */
function fmtWhen(iso, t) {
  if (!iso) return t("upd.never");
  try {
    return new Date(iso).toLocaleString();
  } catch (e) {
    return iso;
  }
}
function fmtBytes(value) {
  const n = Number(value || 0);
  if (!n) return "";
  if (n < 1024 * 1024) return Math.max(1, Math.round(n / 1024)) + " KB";
  return (n / (1024 * 1024)).toFixed(n >= 100 * 1024 * 1024 ? 0 : 1) + " MB";
}
function UpdateProgressWindow({
  update,
  onDismiss,
  onRetry,
  t
}) {
  const phase = update.phase || "checking";
  const active = !!update.active;
  const failed = phase === "error";
  const complete = phase === "complete";
  const checking = phase === "checking";
  const pct = Math.max(0, Math.min(100, Number(update.progress || 0)));
  const bytes = update.bytesTotal ? fmtBytes(update.bytesDownloaded) + " / " + fmtBytes(update.bytesTotal) : "";
  const title = failed ? t("upd.modalFailed") : complete ? t("upd.modalCurrent") : phase === "restarting" ? t("upd.modalRestarting") : t("upd.modalTitle");
  const message = update.message || (checking ? t("upd.modalChecking") : t("upd.modalPreparing"));
  return React.createElement("div", {
    className: "update-modal-backdrop",
    role: "presentation"
  }, React.createElement("section", {
    className: "update-modal" + (failed ? " failed" : ""),
    role: "dialog",
    "aria-modal": "true",
    "aria-live": "polite",
    "aria-label": title
  }, React.createElement("div", {
    className: "update-modal-glow"
  }), React.createElement("div", {
    className: "update-modal-brand"
  }, React.createElement("span", {
    className: "update-modal-mark"
  }, React.createElement("img", {
    src: "AlphaPOS.png",
    alt: ""
  })), React.createElement("span", null, React.createElement("b", null, "ALPHA POS"), React.createElement("small", null, t("upd.secureUpdate")))), React.createElement("div", {
    className: "update-modal-body"
  }, React.createElement("div", {
    className: "update-orbit" + (failed || complete ? " still" : ""),
    "aria-hidden": "true"
  }, React.createElement("i", null), React.createElement("i", null), React.createElement("i", null), React.createElement("span", {
    className: !failed && !complete ? "has-logo" : ""
  }, failed ? "!" : complete ? "✓" : React.createElement("img", {
    src: "AlphaPOS.png",
    alt: ""
  }))), React.createElement("h2", null, title), React.createElement("p", null, message), React.createElement("div", {
    className: "update-progress-track" + (checking ? " indeterminate" : "")
  }, React.createElement("i", {
    style: checking ? null : {
      width: pct + "%"
    }
  })), React.createElement("div", {
    className: "update-progress-meta"
  }, React.createElement("span", null, bytes || (update.targetVersion ? "v" + update.targetVersion : t("upd.signedVerified"))), React.createElement("b", null, checking ? "" : pct + "%"))), !active ? React.createElement("div", {
    className: "update-modal-actions"
  }, failed && update.retryable ? React.createElement(Btn, {
    variant: "primary",
    icon: "refresh",
    onClick: onRetry
  }, t("upd.tryAgain")) : null, React.createElement(Btn, {
    variant: "ghost",
    onClick: onDismiss
  }, t("common.close"))) : React.createElement("p", {
    className: "update-modal-note"
  }, t("upd.keepOpen"))));
}
function UpdatesScreen() {
  const app = useApp();
  const {
    t,
    updates: u
  } = app;
  const [busy, setBusy] = React.useState(false);
  const [showProgress, setShowProgress] = React.useState(false);
  const buildMode = !u.frozen ? t("upd.dev") : u.enabled ? t("upd.installed") : t("upd.disabledMode");
  const newAvail = !!(u.available && u.available !== u.version);
  React.useEffect(() => {
    if (u.active) setShowProgress(true);
  }, [u.active]);
  React.useEffect(() => {
    if (!showProgress || !u.active) return undefined;
    const poll = window.setInterval(() => u.refresh(), 350);
    return () => window.clearInterval(poll);
  }, [showProgress, u.active, u.refresh]);
  const doCheck = async () => {
    setBusy(true);
    try {
      await u.checkOnly();
    } finally {
      setBusy(false);
    }
  };
  const doInstall = async () => {
    setBusy(true);
    try {
      const result = await u.install();
      if (result && (result.started || result.busy)) setShowProgress(true);
    } finally {
      setBusy(false);
    }
  };
  const retry = async () => {
    setShowProgress(false);
    await doInstall();
  };
  return React.createElement("div", {
    className: "page",
    "data-screen-label": "Updates"
  }, React.createElement("header", {
    className: "page-head"
  }, React.createElement("h1", {
    className: "page-h"
  }, t("nav.updates")), React.createElement("p", {
    className: "page-sub"
  }, t("upd.sub"))), React.createElement("div", {
    className: "stack"
  }, React.createElement(Card, {
    title: t("upd.current"),
    action: u.active ? React.createElement(Badge, {
      tone: "warn"
    }, t("upd.installing")) : u.pending ? React.createElement(Badge, {
      tone: "warn"
    }, t("upd.pending")) : newAvail ? React.createElement(Badge, {
      tone: "warn"
    }, t("upd.newAvailable")) : React.createElement(Badge, {
      tone: "ok"
    }, t("upd.upToDate"))
  }, React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "auto 1fr",
      gap: "4px 40px",
      alignItems: "end"
    }
  }, React.createElement("div", null, React.createElement("div", {
    className: "kv-l",
    style: {
      fontSize: 13,
      color: "var(--ink-3)"
    }
  }, t("upd.version")), React.createElement("div", {
    className: "stat-big"
  }, "v", u.version)), React.createElement("div", {
    className: "kv"
  }, React.createElement(KRow, {
    l: t("upd.mode"),
    v: buildMode
  }), React.createElement(KRow, {
    l: t("upd.server"),
    v: u.url || t("common.none"),
    mono: true,
    dim: !u.url
  }), React.createElement(KRow, {
    l: t("upd.availableV"),
    v: u.available ? "v" + u.available : t("upd.upToDate"),
    mono: !!u.available
  }))), React.createElement("div", {
    className: "kv",
    style: {
      marginTop: 16
    }
  }, React.createElement(KRow, {
    l: t("upd.lastChecked"),
    v: fmtWhen(u.lastCheckAt, t),
    dim: !u.lastCheckAt
  }), React.createElement(KRow, {
    l: t("upd.lastUpdated"),
    v: u.lastUpdateAt ? fmtWhen(u.lastUpdateAt, t) + (u.lastUpdateVersion ? "  ·  v" + u.lastUpdateVersion : "") : t("upd.never"),
    dim: !u.lastUpdateAt
  })), u.lastCheckError ? React.createElement("p", {
    style: {
      margin: "10px 0 0",
      color: "var(--warn)",
      fontSize: 12.5
    }
  }, u.lastCheckError) : null, u.pending ? React.createElement("p", {
    style: {
      margin: "10px 0 0",
      color: "var(--warn)",
      fontSize: 13
    }
  }, t("upd.pendingMsg")) : null, React.createElement("div", {
    className: "hstack",
    style: {
      marginTop: 18
    }
  }, React.createElement(Btn, {
    variant: "ghost",
    icon: "refresh",
    onClick: doCheck,
    disabled: busy || u.active
  }, busy ? t("upd.checking") : t("upd.checkNow")), React.createElement(Btn, {
    variant: "primary",
    icon: "download",
    onClick: doInstall,
    disabled: busy || u.active || !newAvail
  }, u.active ? t("upd.installing") : t("upd.installNow"))), React.createElement("p", {
    style: {
      margin: "12px 0 0",
      color: "var(--ink-3)",
      fontSize: 12.5
    }
  }, t("upd.auto"))), React.createElement(Card, {
    title: t("upd.history")
  }, !u.history || u.history.length === 0 ? React.createElement("p", {
    style: {
      color: "var(--ink-3)",
      fontSize: 13,
      margin: "2px 0"
    }
  }, t("upd.noHistory")) : React.createElement("div", {
    className: "kv"
  }, u.history.slice().reverse().map((h, i) => React.createElement(KRow, {
    key: i,
    l: fmtWhen(h.at, t),
    v: "v" + h.version,
    mono: true
  }))))), showProgress ? React.createElement(UpdateProgressWindow, {
    update: u,
    t: t,
    onRetry: retry,
    onDismiss: () => setShowProgress(false)
  }) : null);
}
Object.assign(window, {
  UpdatesScreen
});

/* source: app/screens-logs.jsx */
function logLevelClass(level) {
  const l = String(level || "").toUpperCase();
  if (l === "ERROR" || l === "CRITICAL") return "error";
  if (l === "WARNING") return "warning";
  if (l === "DEBUG") return "debug";
  return "info";
}
function logTs(ts) {
  return String(ts || "").replace(/[.,]\d+$/, "");
}
function LogsScreen() {
  const app = useApp();
  const {
    t
  } = app;
  const [source, setSource] = React.useState("app");
  const [filter, setFilter] = React.useState("all");
  const [query, setQuery] = React.useState("");
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [auto, setAuto] = React.useState(false);
  const load = React.useCallback(src => {
    setLoading(true);
    return api.app_logs(src, 800).then(r => {
      if (r && r.ok) setData(r);else setData({
        exists: false,
        entries: [],
        counts: {
          total: 0,
          error: 0,
          warning: 0,
          info: 0
        },
        error: r && r.error
      });
      setLoading(false);
    });
  }, []);
  React.useEffect(() => {
    load(source);
  }, [load, source]);
  React.useEffect(() => {
    if (!auto) return;
    const id = setInterval(() => load(source), 5000);
    return () => clearInterval(id);
  }, [auto, source, load]);
  const counts = data && data.counts || {
    total: 0,
    error: 0,
    warning: 0,
    info: 0
  };
  const entries = data && data.entries || [];
  const q = query.trim().toLowerCase();
  const rows = entries.map((e, i) => ({
    ...e,
    _i: i,
    cls: logLevelClass(e.level)
  })).reverse().filter(e => {
    if (filter === "error" && e.cls !== "error") return false;
    if (filter === "warning" && e.cls !== "warning") return false;
    if (filter === "info" && (e.cls === "error" || e.cls === "warning")) return false;
    if (q && !((e.message || "").toLowerCase().includes(q) || (e.logger || "").toLowerCase().includes(q) || (e.level || "").toLowerCase().includes(q))) return false;
    return true;
  });
  const chips = [{
    k: "all",
    label: t("log.all"),
    n: counts.total,
    tone: ""
  }, {
    k: "error",
    label: t("log.errors"),
    n: counts.error,
    tone: "error"
  }, {
    k: "warning",
    label: t("log.warnings"),
    n: counts.warning,
    tone: "warning"
  }, {
    k: "info",
    label: t("log.info"),
    n: counts.info,
    tone: "info"
  }];
  return React.createElement("div", {
    className: "page",
    "data-screen-label": "Logs"
  }, React.createElement("header", {
    className: "page-head",
    style: {
      display: "flex",
      alignItems: "flex-end",
      justifyContent: "space-between",
      gap: 16,
      flexWrap: "wrap"
    }
  }, React.createElement("div", null, React.createElement("h1", {
    className: "page-h"
  }, t("log.title")), React.createElement("p", {
    className: "page-sub"
  }, t("log.sub"))), React.createElement("div", {
    className: "hstack"
  }, React.createElement(Seg, {
    value: source,
    onChange: setSource,
    options: [{
      v: "app",
      l: t("log.srcApp")
    }, {
      v: "error",
      l: t("log.srcError")
    }]
  }), React.createElement("button", {
    className: "btn btn-ghost btn-sm" + (auto ? " on" : ""),
    onClick: () => setAuto(a => !a),
    "aria-pressed": auto
  }, React.createElement("span", {
    className: "dot" + (auto ? " pulse" : ""),
    style: {
      background: auto ? "var(--ok)" : "var(--ink-3)"
    }
  }), t("log.live")), React.createElement(Btn, {
    variant: "ghost",
    size: "sm",
    icon: "refresh",
    onClick: () => load(source),
    disabled: loading
  }, loading ? t("common.running") : t("log.refresh")))), React.createElement(Card, null, React.createElement("div", {
    className: "log-toolbar"
  }, React.createElement("div", {
    className: "log-chips"
  }, chips.map(c => React.createElement("button", {
    key: c.k,
    className: "log-chip" + (c.tone ? " " + c.tone : "") + (filter === c.k ? " on" : ""),
    onClick: () => setFilter(c.k)
  }, React.createElement("span", {
    className: "log-chip-dot"
  }), c.label, React.createElement("span", {
    className: "log-chip-n"
  }, c.n)))), React.createElement("div", {
    className: "log-search"
  }, React.createElement(Icon, {
    name: "search",
    size: 15
  }), React.createElement("input", {
    className: "inp",
    placeholder: t("log.searchPh"),
    value: query,
    onChange: e => setQuery(e.target.value)
  }), query ? React.createElement("button", {
    className: "copy-btn",
    onClick: () => setQuery(""),
    "aria-label": "Clear",
    title: "Clear"
  }, React.createElement(Icon, {
    name: "close",
    size: 13
  })) : null)), data && data.exists === false ? React.createElement("div", {
    className: "log-empty"
  }, data.error ? data.error : t("log.noFile")) : rows.length === 0 ? React.createElement("div", {
    className: "log-empty"
  }, entries.length ? t("log.noMatch") : t("log.empty")) : React.createElement("div", {
    className: "log-list"
  }, rows.map(e => React.createElement("div", {
    key: e._i,
    className: "log-row lvl-" + e.cls
  }, React.createElement("span", {
    className: "log-ts mono"
  }, logTs(e.ts)), React.createElement("span", {
    className: "log-lvl " + e.cls
  }, e.level), React.createElement("span", {
    className: "log-body"
  }, React.createElement("span", {
    className: "log-logger mono"
  }, e.logger), React.createElement("span", {
    className: "log-text"
  }, e.message))))), React.createElement("div", {
    className: "log-foot"
  }, React.createElement("span", null, t("log.showing"), " ", rows.length, rows.length !== entries.length ? " / " + entries.length : ""), data && data.path ? React.createElement("span", {
    className: "mono log-path",
    title: data.path
  }, data.path) : null)));
}
Object.assign(window, {
  LogsScreen
});

/* source: app/main.jsx */
const DIRECTIONS = ["Porcelain", "Noir", "Atelier"];
const ACCENTS = ["#1e6b4c", "#27486e", "#8a4a2c", "#5b4a7a"];
const SYNC_L = {
  en: {
    live: "Sync live",
    off: "Sync off",
    down: "Not connected",
    busy: "Syncing…",
    pending: "queued"
  },
  uz: {
    live: "Sinx faol",
    off: "Sinx o‘chiq",
    down: "Ulanmagan",
    busy: "Sinxlash…",
    pending: "navbatda"
  },
  ru: {
    live: "Синхр. активна",
    off: "Синхр. выкл",
    down: "Нет связи",
    busy: "Синхр…",
    pending: "в очереди"
  }
};
const NAV = [{
  id: "dashboard",
  icon: "dashboard",
  l: "nav.dashboard",
  screen: () => React.createElement(DashboardScreen, null)
}, {
  id: "license",
  icon: "license",
  l: "nav.license",
  screen: () => React.createElement(LicenseScreen, null)
}, {
  id: "config",
  icon: "sliders",
  l: "nav.config",
  screen: () => React.createElement(ConfigScreen, null)
}, {
  id: "tests",
  icon: "flask",
  l: "nav.tests",
  screen: () => React.createElement(TestsScreen, null)
}, {
  id: "fiscal",
  icon: "receipt",
  l: "nav.fiscal",
  screen: () => React.createElement(FiscalScreen, null)
}, {
  id: "logs",
  icon: "logs",
  l: "nav.logs",
  screen: () => React.createElement(LogsScreen, null)
}, {
  id: "updates",
  icon: "download",
  l: "nav.updates",
  screen: () => React.createElement(UpdatesScreen, null)
}];
function fmtClock(d) {
  if (!d) return "—";
  const z = n => String(n).padStart(2, "0");
  return z(d.getHours()) + ":" + z(d.getMinutes()) + ":" + z(d.getSeconds());
}
function fmtUptime(s) {
  const z = n => String(n).padStart(2, "0");
  return z(Math.floor(s / 3600)) + ":" + z(Math.floor(s % 3600 / 60)) + ":" + z(s % 60);
}
function daysBetween(iso) {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (isNaN(then)) return null;
  return Math.max(0, Math.round((then - Date.now()) / 86400000));
}
function App() {
  const [dir, setDirRaw] = React.useState("porcelain");
  const [accent, setAccentRaw] = React.useState(ACCENTS[0]);
  const [lang, setLangRaw] = React.useState("en");
  const prefsLoaded = React.useRef(false);
  React.useEffect(() => {
    api.get_ui_prefs().then(r => {
      const p = r && r.prefs || {};
      if (p.dir) setDirRaw(p.dir);
      if (p.accent) setAccentRaw(p.accent);
      if (p.lang) setLangRaw(p.lang);
      prefsLoaded.current = true;
    });
  }, []);
  const persist = patch => {
    if (prefsLoaded.current) api.set_ui_prefs(patch);
  };
  const setDir = v => {
    const d = v.toLowerCase();
    setDirRaw(d);
    persist({
      dir: d
    });
  };
  const setAccent = v => {
    setAccentRaw(v);
    persist({
      accent: v
    });
  };
  const setLang = v => {
    const l = v.toLowerCase();
    setLangRaw(l);
    persist({
      lang: l
    });
  };
  const t = React.useCallback(k => window.tr(lang, k), [lang]);
  const sl = SYNC_L[lang] || SYNC_L.en;
  React.useEffect(() => {
    document.documentElement.setAttribute("data-dir", dir);
  }, [dir]);
  React.useEffect(() => {
    if (dir === "porcelain" && accent) document.documentElement.style.setProperty("--accent", accent);else document.documentElement.style.removeProperty("--accent");
  }, [dir, accent]);
  const [page, setPage] = React.useState("dashboard");
  const [tick, setTick] = React.useState(0);
  React.useEffect(() => {
    const id = setInterval(() => setTick(x => x + 1), 1000);
    return () => clearInterval(id);
  }, []);
  const [toasts, setToasts] = React.useState([]);
  const toast = msg => {
    const id = Math.random().toString(36).slice(2);
    setToasts(ts => [...ts, {
      id,
      msg
    }]);
    setTimeout(() => setToasts(ts => ts.filter(x => x.id !== id)), 2600);
  };
  const [srv, setSrv] = React.useState({
    running: false,
    port: 8000,
    lan_ip: "127.0.0.1"
  });
  const [phase, setPhase] = React.useState("off");
  const [lic, setLic] = React.useState(null);
  const [fiscal, setFiscal] = React.useState({
    mode: "off",
    provider: "mock",
    confirmed: 0,
    failed: 0
  });
  const [creds, setCreds] = React.useState({
    email: "",
    password: ""
  });
  const [upd, setUpd] = React.useState({
    version: "1.0.0",
    update_url: "",
    pending: false,
    frozen: false
  });
  const [sync, setSync] = React.useState({
    enabled: false,
    pending_count: 0
  });
  const [syncBusy, setSyncBusy] = React.useState(false);
  const onSinceRef = React.useRef(null);
  const refreshServer = React.useCallback(() => {
    return api.server_status().then(r => {
      if (!r || r.ok === false) return;
      setSrv(r);
      setPhase(ph => ph === "starting" || ph === "stopping" ? ph : r.running ? "on" : "off");
      if (r.running && onSinceRef.current == null) onSinceRef.current = Date.now();
      if (!r.running) onSinceRef.current = null;
    });
  }, []);
  const refreshLicense = React.useCallback(() => api.license_status().then(r => {
    if (r && r.license) setLic(r.license);
  }), []);
  const refreshFiscal = React.useCallback(() => api.fiscal_status().then(r => {
    if (r && r.fiscal) setFiscal(f => ({
      ...f,
      ...r.fiscal
    }));
  }), []);
  const refreshCreds = React.useCallback(() => api.admin_credentials().then(r => {
    if (r && r.ok) setCreds({
      email: r.email,
      password: r.password
    });
  }), []);
  const refreshUpdates = React.useCallback(() => api.update_status().then(r => {
    if (r && r.ok) setUpd(r);
  }), []);
  const refreshSync = React.useCallback(() => api.sync_status().then(r => {
    if (r && r.ok && r.sync) setSync(r.sync);
  }), []);
  const refreshAll = React.useCallback(() => {
    refreshServer();
    refreshLicense();
    refreshFiscal();
    refreshCreds();
    refreshUpdates();
    refreshSync();
  }, [refreshServer, refreshLicense, refreshFiscal, refreshCreds, refreshUpdates, refreshSync]);
  React.useEffect(() => {
    refreshAll();
  }, [refreshAll]);
  React.useEffect(() => {
    if (tick > 0 && tick % 4 === 0) refreshServer();
    if (tick > 0 && tick % 5 === 0) refreshSync();
    if (tick > 0 && tick % 20 === 0) {
      refreshLicense();
      refreshUpdates();
    }
  }, [tick, refreshServer, refreshLicense, refreshUpdates, refreshSync]);
  const toggleServer = async () => {
    if (phase === "on") {
      setPhase("stopping");
      await api.stop_server();
      onSinceRef.current = null;
      setPhase("off");
      refreshServer();
    } else if (phase === "off") {
      setPhase("starting");
      const setup = await api.run_setup();
      if (!setup || !setup.ok) {
        setPhase("off");
        toast(setup && setup.error || "Setup failed");
        refreshAll();
        return;
      }
      const r = await api.start_server();
      if (r && r.running) {
        onSinceRef.current = Date.now();
        setPhase("on");
        toast(t("dash.serverOn"));
      } else {
        setPhase("off");
        toast(r && r.error || "Start failed");
      }
      refreshAll();
    }
  };
  const cloudSyncNow = async () => {
    if (syncBusy) return;
    setSyncBusy(true);
    const r = await api.cloud_sync_now();
    setSyncBusy(false);
    refreshSync();
    toast(r && r.ok ? sl.live + " ✓" : sl.down + (r && r.error ? ": " + r.error : ""));
  };
  const uptime = onSinceRef.current ? Math.floor((Date.now() - onSinceRef.current) / 1000) : 0;
  const registered = !!(lic && lic.status === "ACTIVE");
  const daysLeft = lic ? lic.days_remaining != null ? lic.days_remaining : daysBetween(lic.expires_at) : null;
  const pct = daysLeft != null ? Math.max(0, Math.min(100, Math.round(daysLeft / 365 * 100))) : 0;
  const activateLicense = async over => {
    const r = await api.license_register(over.email || lic && lic.email || "", over.plan || null);
    if (r && r.ok) toast(t("lic.registered"));else toast(r && r.data && r.data.message || t("lic.needsUrl"));
    refreshLicense();
  };
  const deactivateLicense = async () => {
    await api.license_deactivate();
    toast(t("lic.deactivated"));
    refreshLicense();
  };
  const heartbeatNow = async () => {
    const r = await api.license_heartbeat_now();
    toast(r && r.ok ? t("common.justNow") + " · " + t("lic.heartbeat") + " ✓" : t("dash.lastError"));
    refreshLicense();
  };
  const setFisMode = async m => {
    setFiscal(f => ({
      ...f,
      mode: m
    }));
    await api.fiscal_set_mode(m);
    refreshFiscal();
  };
  const bumpConfirmed = () => {
    api.fiscal_test().then(() => refreshFiscal());
  };
  const lastBeat = lic && lic.last_heartbeat_at ? new Date(lic.last_heartbeat_at) : null;
  const ccUrl = lic && lic.control_center_url || "";
  const controlHost = ccUrl ? ccUrl.replace(/^https?:\/\//, "").replace(/\/.*$/, "") : "—";
  const lastMessage = lic && lic.last_message ? lic.last_message : "";
  const licStatus = lic && lic.status;
  const hbWorker = (srv.workers || {}).heartbeat || {};
  const hbIsError = licStatus === "SUSPENDED" || licStatus === "EXPIRED";
  const hbHealthy = registered && !!hbWorker.alive && !hbWorker.last_error;
  const ctx = {
    t,
    lang,
    toast,
    nav: setPage,
    cfg: {
      port: srv.port || 8000,
      lanIp: srv.lan_ip || "127.0.0.1",
      controlHost
    },
    server: {
      phase,
      toggle: toggleServer,
      uptimeStr: fmtUptime(uptime),
      error: (srv.environment || {}).error || (srv.database || {}).error || (srv.database || {}).warning || srv.last_error || ""
    },
    hb: {
      online: hbHealthy,
      hasBeat: !!lastBeat,
      canSync: registered,
      status: licStatus,
      pending: sync.pending_count || 0,
      alive: !!hbWorker.alive,
      nextIn: hbWorker.next_run_in_s,
      lastBeatStr: lastBeat ? fmtClock(lastBeat) : "—",
      lastError: hbWorker.last_error || (hbIsError ? lastMessage : ""),
      warn: !!(lic && lic.warn),
      syncNow: heartbeatNow
    },
    lic: {
      registered,
      org: lic && lic.org_name || "—",
      plan: lic && lic.plan || (registered ? "Licensed" : "—"),
      expires: lic && lic.expires_at ? lic.expires_at.slice(0, 10) : "—",
      daysLeft: daysLeft != null ? daysLeft : "—",
      pct,
      balance: lic && lic.balance != null ? lic.balance : "—",
      status: lic && lic.status,
      lastMessage,
      warn: !!(lic && lic.warn)
    },
    fiscal: {
      mode: fiscal.mode,
      setMode: setFisMode,
      provider: fiscal.provider || "mock",
      confirmed: fiscal.confirmed || 0,
      failed: fiscal.failed || 0,
      bumpConfirmed
    },
    adminCreds: creds,
    updates: {
      version: upd.version,
      url: upd.update_url,
      pending: upd.pending,
      frozen: upd.frozen,
      enabled: upd.enabled,
      reason: upd.reason,
      active: !!upd.active,
      phase: upd.phase || "idle",
      progress: Number(upd.progress || 0),
      message: upd.message || "",
      bytesDownloaded: Number(upd.bytes_downloaded || 0),
      bytesTotal: Number(upd.bytes_total || 0),
      targetVersion: upd.target_version,
      retryable: !!upd.retryable,
      lastCheckAt: upd.last_check_at,
      lastCheckOk: upd.last_check_ok,
      lastCheckError: upd.last_check_error,
      lastUpdateAt: upd.last_update_at,
      lastUpdateVersion: upd.last_update_version,
      available: upd.available,
      history: upd.history || [],
      checkOnly: async () => {
        const r = await api.check_updates_only();
        await refreshUpdates();
        if (r && r.error) toast(r.error);else if (r && r.busy) toast(t("upd.checking"));else if (r && r.available && r.available !== upd.version) toast(t("upd.newAvailable"));else if (r && r.enabled !== false) toast(t("upd.upToDate"));
        return r;
      },
      install: async () => {
        const r = await api.check_updates_now();
        await refreshUpdates();
        return r;
      },
      refresh: refreshUpdates
    },
    activateLicense,
    deactivateLicense,
    refreshAll
  };
  const active = NAV.find(n => n.id === page) || NAV[0];
  return React.createElement(AppCtx.Provider, {
    value: ctx
  }, React.createElement("div", {
    className: "apb"
  }, React.createElement("div", {
    className: "titlebar"
  }, React.createElement("div", {
    className: "tb-app"
  }, React.createElement("img", {
    className: "tb-logo",
    src: "AlphaPOS.png",
    alt: ""
  }), "Alpha POS Backend"), React.createElement("div", {
    className: "tb-spacer"
  }), React.createElement(SyncPill, {
    sync: sync,
    busy: syncBusy,
    onSync: cloudSyncNow,
    sl: sl
  })), React.createElement("div", {
    className: "frame"
  }, React.createElement("aside", {
    className: "sidebar"
  }, React.createElement("div", {
    className: "wordmark"
  }, React.createElement("img", {
    className: "wm-logo",
    src: "AlphaPOS.png",
    alt: "Alpha POS"
  }), React.createElement("div", {
    className: "wm-copy"
  }, React.createElement("div", {
    className: "wm-name"
  }, "Alpha POS"), React.createElement("div", {
    className: "wm-sub"
  }, "Backend"))), React.createElement("nav", {
    className: "nav"
  }, NAV.map(n => React.createElement("button", {
    key: n.id,
    className: "nav-item" + (n.id === page ? " active" : ""),
    onClick: () => setPage(n.id)
  }, React.createElement(Icon, {
    name: n.icon
  }), t(n.l)))), React.createElement("div", {
    className: "side-foot"
  }, React.createElement("div", {
    className: "side-server"
  }, React.createElement("span", {
    className: "dot",
    style: {
      color: phase === "on" ? "var(--ok)" : "var(--ink-3)",
      background: "currentColor"
    }
  }), React.createElement("span", {
    style: {
      flex: 1
    }
  }, phase === "on" ? t("common.online") : t("common.offline")), phase === "on" && React.createElement("span", {
    className: "mono",
    style: {
      fontSize: 11.5,
      color: "var(--ink-3)"
    }
  }, ":", srv.port)), React.createElement("div", {
    className: "lang-seg"
  }, ["EN", "UZ", "RU"].map(L => React.createElement("button", {
    key: L,
    className: lang === L.toLowerCase() ? "active" : "",
    onClick: () => setLang(L)
  }, L))), React.createElement(ThemeSwitch, {
    dir: dir,
    setDir: setDir,
    accent: accent,
    setAccent: setAccent,
    t: t
  }), React.createElement("div", {
    className: "side-ver"
  }, "v", upd.version, " \xB7 single-PC install"))), React.createElement("main", {
    className: "main"
  }, React.createElement(React.Fragment, {
    key: page + lang
  }, active.screen()))), React.createElement("div", {
    className: "toast-wrap"
  }, toasts.map(x => React.createElement("div", {
    key: x.id,
    className: "toast"
  }, React.createElement("span", {
    className: "dot"
  }), x.msg)))));
}
function ThemeSwitch({
  dir,
  setDir,
  accent,
  setAccent,
  t
}) {
  return React.createElement("div", {
    className: "theme-switch"
  }, React.createElement("div", {
    className: "ts-seg"
  }, DIRECTIONS.map(d => React.createElement("button", {
    key: d,
    className: dir === d.toLowerCase() ? "active" : "",
    title: d,
    onClick: () => setDir(d)
  }, d[0]))), dir === "porcelain" && React.createElement("div", {
    className: "ts-accents"
  }, ACCENTS.map(c => React.createElement("button", {
    key: c,
    className: "ts-acc" + (accent === c ? " on" : ""),
    style: {
      background: c
    },
    onClick: () => setAccent(c),
    "aria-label": "Accent " + c
  }))));
}
function SyncPill({
  sync,
  busy,
  onSync,
  sl
}) {
  const enabled = !!sync.enabled;
  const online = enabled && !!sync.is_online;
  const color = !enabled ? "var(--ink-3)" : online ? "var(--ok)" : "#d23b3b";
  const label = busy ? sl.busy : !enabled ? sl.off : online ? sl.live : sl.down;
  const pending = sync.pending_count || 0;
  const title = [label, pending ? pending + " " + sl.pending : "", sync.last_error || ""].filter(Boolean).join("   ·   ");
  return React.createElement("button", {
    title: title,
    onClick: onSync,
    disabled: busy,
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 7,
      background: "transparent",
      border: "1px solid rgba(127,127,127,.28)",
      borderRadius: 999,
      padding: "4px 11px",
      marginRight: 4,
      cursor: busy ? "default" : "pointer",
      font: "inherit",
      fontSize: 12,
      color: "var(--ink-2, inherit)",
      opacity: busy ? 0.7 : 1
    }
  }, React.createElement("span", {
    style: {
      width: 8,
      height: 8,
      borderRadius: "50%",
      background: color,
      transition: "background .3s"
    }
  }), React.createElement(Icon, {
    name: "refresh"
  }), React.createElement("span", null, label), pending ? React.createElement("span", {
    className: "mono",
    style: {
      opacity: 0.65
    }
  }, "\xB7 ", pending) : null);
}
ReactDOM.createRoot(document.getElementById("root")).render(React.createElement(App, null));
})();
