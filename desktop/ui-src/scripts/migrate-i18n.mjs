// One-time migration: evaluate the legacy desktop/ui/app/i18n.js (with a window
// stub) plus the SYNC_L / LOCAL_AUDIT_L tables that lived in main.jsx and
// screens-admin.jsx, drop retired keys, merge the new keys, and write typed
// src/i18n/{en,uz,ru}.ts. Deleted after the cutover.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const legacy = path.resolve(here, '../../ui/app');
const outDir = path.resolve(here, '../src/i18n');

const window = {};
vm.runInNewContext(fs.readFileSync(path.join(legacy, 'i18n.js'), 'utf8'), { window });

function extractObject(file, name) {
  const src = fs.readFileSync(path.join(legacy, file), 'utf8');
  const start = src.indexOf(`const ${name} = {`);
  if (start < 0) throw new Error(`${name} not found in ${file}`);
  let depth = 0;
  let i = src.indexOf('{', start);
  const begin = i;
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (depth === 0) break; }
  }
  return vm.runInNewContext('(' + src.slice(begin, i + 1) + ')');
}

const DROP = [/^ntf\./, /^ev\./, /^side\./, /^upd\.modal/, /^common\.minAgo$/];

// [en, uz, ru]
const OVERRIDES = {
  'nav.tests': ['Tests & Recovery', 'Testlar va tiklash', 'Тесты и восстановление'],
  'tests.t9': ['Pull cloud changes', 'Bulutdan o‘zgarishlarni olish', 'Получить изменения из облака'],
  'tests.t9d': ['Download changes from the cloud hub', 'Bulut markazidan o‘zgarishlarni yuklab olish', 'Загрузить изменения с облачного хаба'],
};

const ADD = {
  'chip.running': ['Running', 'Ishlayapti', 'Работает'],
  'chip.stopped': ['Stopped', 'To‘xtagan', 'Остановлен'],
  'chip.starting': ['Starting…', 'Ishga tushmoqda…', 'Запуск…'],
  'chip.stopping': ['Stopping…', 'To‘xtatilmoqda…', 'Остановка…'],
  'chip.booting': ['Preparing…', 'Tayyorlanmoqda…', 'Подготовка…'],
  'chip.connecting': ['Connecting…', 'Ulanmoqda…', 'Подключение…'],
  'chip.unreachable': ['Unreachable', 'Aloqa yo‘q', 'Недоступен'],
  'chip.error': ['Error', 'Xato', 'Ошибка'],
  'chip.update': ['Update', 'Yangilanish', 'Обновление'],
  'chip.serverLabel': ['Server status', 'Server holati', 'Статус сервера'],
  'chip.syncLabel': ['Cloud sync', 'Bulut sinxronizatsiyasi', 'Облачная синхронизация'],
  'chip.tunnelLabel': ['Support tunnel', 'Yordam tunneli', 'Туннель поддержки'],
  'chip.auditLabel': ['Order evidence', 'Buyurtma dalillari', 'Данные заказов'],
  'phase.connecting': ['Connecting to the control service…', 'Boshqaruv xizmatiga ulanmoqda…', 'Подключение к службе управления…'],
  'phase.unreachable': ['Control service unreachable', 'Boshqaruv xizmati bilan aloqa yo‘q', 'Служба управления недоступна'],
  'phase.booting': ['Preparing database…', 'Ma’lumotlar bazasi tayyorlanmoqda…', 'Подготовка базы данных…'],
  'phase.error': ['Server stopped with an error', 'Server xato bilan to‘xtadi', 'Сервер остановлен с ошибкой'],
  'phase.bootingSub': ['The backend is getting ready. This can take a minute.', 'Backend tayyorlanmoqda. Bu bir daqiqa davom etishi mumkin.', 'Бэкенд готовится. Это может занять минуту.'],
  'phase.unreachableSub': ['The panel cannot reach the local control service. Retrying automatically.', 'Panel lokal boshqaruv xizmatiga ulana olmayapti. Avtomatik qayta urinilmoqda.', 'Панель не может связаться с локальной службой управления. Повтор автоматически.'],
  'phase.errorSub': ['Fix the problem below, then start the server again.', 'Quyidagi muammoni tuzating va serverni qayta ishga tushiring.', 'Устраните проблему ниже и снова запустите сервер.'],
  'dash.server': ['Server', 'Server', 'Сервер'],
  'dash.start': ['Start server', 'Serverni ishga tushirish', 'Запустить сервер'],
  'dash.stop': ['Stop server', 'Serverni to‘xtatish', 'Остановить сервер'],
  'dash.startFailed': ['Could not start the server', 'Serverni ishga tushirib bo‘lmadi', 'Не удалось запустить сервер'],
  'dash.stopFailed': ['Could not stop the server', 'Serverni to‘xtatib bo‘lmadi', 'Не удалось остановить сервер'],
  'dash.setupFailed': ['Setup failed', 'Tayyorlash muvaffaqiyatsiz', 'Ошибка подготовки'],
  'dash.cloudSync': ['Cloud sync', 'Bulut sinxronizatsiyasi', 'Облачная синхронизация'],
  'dash.lastPush': ['Last push', 'Oxirgi yuborish', 'Последняя отправка'],
  'dash.lastPull': ['Last pull', 'Oxirgi olish', 'Последнее получение'],
  'dash.syncOk': ['Cloud sync finished', 'Bulut sinxronizatsiyasi yakunlandi', 'Синхронизация завершена'],
  'dash.heartbeatNow': ['Heartbeat now', 'Hozir signal yuborish', 'Отправить сигнал'],
  'dash.heartbeatOk': ['Heartbeat sent', 'Signal yuborildi', 'Сигнал отправлен'],
  'dash.heartbeatFailed': ['Heartbeat failed', 'Signal yuborilmadi', 'Сигнал не отправлен'],
  'dash.observability': ['Support & evidence', 'Yordam va dalillar', 'Поддержка и данные'],
  'dash.technical': ['Technical details', 'Texnik tafsilotlar', 'Технические детали'],
  'common.retry': ['Retry', 'Qayta urinish', 'Повторить'],
  'common.loading': ['Loading…', 'Yuklanmoqda…', 'Загрузка…'],
  'common.loadFailed': ['Could not load this data', 'Ma’lumotni yuklab bo‘lmadi', 'Не удалось загрузить данные'],
  'common.stale': ['Showing the last known data — refresh failed.', 'Oxirgi ma’lum ma’lumot ko‘rsatilmoqda — yangilash muvaffaqiyatsiz.', 'Показаны последние данные — обновление не удалось.'],
  'common.empty': ['Nothing to show yet.', 'Hozircha ko‘rsatadigan narsa yo‘q.', 'Пока нечего показать.'],
  'common.cancel': ['Cancel', 'Bekor qilish', 'Отмена'],
  'common.discard': ['Discard changes', 'O‘zgarishlarni bekor qilish', 'Отменить изменения'],
  'common.stay': ['Stay', 'Qolish', 'Остаться'],
  'common.unsavedTitle': ['Unsaved changes', 'Saqlanmagan o‘zgarishlar', 'Несохранённые изменения'],
  'common.unsavedBody': ['You have unsaved changes on this page. Leave and discard them?', 'Bu sahifada saqlanmagan o‘zgarishlar bor. Chiqib, ularni bekor qilasizmi?', 'На этой странице есть несохранённые изменения. Уйти и отменить их?'],
  'common.changed': ['{n} unsaved changes', '{n} ta saqlanmagan o‘zgarish', 'Несохранённых изменений: {n}'],
  'common.saving': ['Saving…', 'Saqlanmoqda…', 'Сохранение…'],
  'common.failed': ['Action failed', 'Amal bajarilmadi', 'Действие не выполнено'],
  'common.saveFailed': ['Save failed', 'Saqlash muvaffaqiyatsiz', 'Ошибка сохранения'],
  'common.testFailed': ['Test failed', 'Test muvaffaqiyatsiz', 'Тест не пройден'],
  'common.refresh': ['Refresh', 'Yangilash', 'Обновить'],
  'common.version': ['Version', 'Versiya', 'Версия'],
  'common.language': ['Language', 'Til', 'Язык'],
  'common.theme': ['Theme', 'Mavzu', 'Тема'],
  'common.navigation': ['Main navigation', 'Asosiy navigatsiya', 'Основная навигация'],
  'common.status': ['Status', 'Holat', 'Статус'],
  'theme.light': ['Light', 'Yorug‘', 'Светлая'],
  'theme.dark': ['Dark', 'Qorong‘i', 'Тёмная'],
  'theme.system': ['System', 'Tizim', 'Системная'],
  'session.expired': ['Panel session expired — reopen the window.', 'Panel seansi tugadi — oynani qayta oching.', 'Сеанс панели истёк — откройте окно заново.'],
  'time.minAgo': ['{n} min ago', '{n} daqiqa oldin', '{n} мин назад'],
  'time.hourAgo': ['{n} h ago', '{n} soat oldin', '{n} ч назад'],
  'time.dayAgo': ['{n} d ago', '{n} kun oldin', '{n} дн назад'],
  'cfg.sections': ['Sections', 'Bo‘limlar', 'Разделы'],
  'cfg.flushConfirm': ['All orders, products, users and shifts will be deleted. Configuration is kept. Continue?', 'Barcha buyurtmalar, mahsulotlar, foydalanuvchilar va smenalar o‘chiriladi. Sozlamalar saqlanadi. Davom etasizmi?', 'Все заказы, товары, пользователи и смены будут удалены. Настройки сохранятся. Продолжить?'],
  'cfg.dangerConfirm': ['Everything on this PC will be deleted permanently. This cannot be undone. Continue?', 'Bu kompyuterdagi hamma narsa butunlay o‘chiriladi. Buni qaytarib bo‘lmaydi. Davom etasizmi?', 'Всё на этом ПК будет удалено навсегда. Это нельзя отменить. Продолжить?'],
  'cfg.secretPh': ['•••••••• (blank keeps it)', '•••••••• (bo‘sh qoldirsangiz saqlanadi)', '•••••••• (пусто — без изменений)'],
  'cfg.exportFailed': ['Export failed', 'Eksport muvaffaqiyatsiz', 'Ошибка экспорта'],
  'cfg.importFailed': ['Import failed', 'Import muvaffaqiyatsiz', 'Ошибка импорта'],
  'fis.modeFailed': ['Could not change the fiscal mode', 'Fiskal rejimni o‘zgartirib bo‘lmadi', 'Не удалось изменить фискальный режим'],
  'log.detail': ['Entry details', 'Yozuv tafsilotlari', 'Детали записи'],
  'log.selectHint': ['Select a line to see the full message.', 'To‘liq xabarni ko‘rish uchun qatorni tanlang.', 'Выберите строку, чтобы увидеть сообщение полностью.'],
  'log.source': ['Log file', 'Log fayli', 'Файл журнала'],
  'log.levels': ['Level filter', 'Daraja filtri', 'Фильтр уровня'],
  'upd.restart': ['Restart to update', 'Yangilash uchun qayta ishga tushirish', 'Перезапустить для обновления'],
  'upd.restartFailed': ['Could not restart to update', 'Yangilash uchun qayta ishga tushirib bo‘lmadi', 'Не удалось перезапустить для обновления'],
  'upd.progress': ['Update progress', 'Yangilanish jarayoni', 'Ход обновления'],
  'upd.checkFailed': ['Update check failed', 'Yangilanishni tekshirib bo‘lmadi', 'Не удалось проверить обновления'],
  'upd.lastError': ['Last check error', 'Oxirgi tekshiruv xatosi', 'Ошибка последней проверки'],
};

const sync = extractObject('main.jsx', 'SYNC_L');
const audit = extractObject('screens-admin.jsx', 'LOCAL_AUDIT_L');
const LANGS = ['en', 'uz', 'ru'];
const dicts = {};
for (const lang of LANGS) {
  const dict = {};
  for (const [k, v] of Object.entries(window.I18N[lang])) {
    if (!DROP.some((re) => re.test(k))) dict[k] = v;
  }
  for (const [k, v] of Object.entries(sync[lang])) dict['sync.' + k] = v;
  for (const [k, v] of Object.entries(audit[lang])) dict['la.' + k] = v;
  dicts[lang] = dict;
}
for (const [k, values] of Object.entries({ ...OVERRIDES, ...ADD })) {
  LANGS.forEach((lang, i) => { dicts[lang][k] = values[i]; });
}
// Retired key referenced only by the old heuristics.
for (const lang of LANGS) {
  for (const key of Object.keys(dicts[lang])) {
    if (!(key in dicts.en)) delete dicts[lang][key];
  }
}

const keys = Object.keys(dicts.en).sort();
const q = (s) => JSON.stringify(s);
fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(
  path.join(outDir, 'en.ts'),
  '// Source of truth for panel strings. uz.ts / ru.ts must define every key.\n'
  + 'const en = {\n' + keys.map((k) => `  ${q(k)}: ${q(dicts.en[k])},`).join('\n') + '\n} as const;\n\nexport default en;\n',
);
for (const lang of ['uz', 'ru']) {
  const missing = keys.filter((k) => dicts[lang][k] == null);
  if (missing.length) throw new Error(`${lang} missing ${missing.join(', ')}`);
  fs.writeFileSync(
    path.join(outDir, `${lang}.ts`),
    "import type en from './en';\n\n"
    + `const ${lang}: Record<keyof typeof en, string> = {\n`
    + keys.map((k) => `  ${q(k)}: ${q(dicts[lang][k])},`).join('\n')
    + `\n};\n\nexport default ${lang};\n`,
  );
}
console.log('wrote', keys.length, 'keys');
