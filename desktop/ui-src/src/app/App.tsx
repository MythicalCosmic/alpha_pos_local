import type { ComponentType } from 'preact';
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'preact/hooks';
import { api } from '../bridge/methods';
import { onAuthError } from '../bridge';
import type { ConfirmModal as ConfirmModalType } from '../components/Modal';
import { Toasts } from '../components/Toasts';
import { Banner, Button, Skeleton } from '../components/ui';
import { I18nContext, loadDict, makeT, type Dict, type Lang } from '../i18n';
import { applyDocumentPrefs, migratePrefs, writeCachedPrefs, type Prefs, type Theme } from '../lib/prefs';
import { router, useRouter, type RouteId } from '../router/router';
import { getLoadedPage, preloadPage } from '../router/routes';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

export function App({ initialPrefs, initialDict }: { initialPrefs: Prefs; initialDict: Dict }) {
  const [prefs, setPrefs] = useState(initialPrefs);
  const [dict, setDict] = useState(initialDict);
  const [expired, setExpired] = useState(false);
  const { route, pending } = useRouter();
  const i18n = useMemo(() => ({ lang: prefs.lang, t: makeT(dict) }), [prefs.lang, dict]);
  const { t } = i18n;
  const serverPrefsLoaded = useRef(false);

  const commitPrefs = (next: Prefs, persist: boolean) => {
    setPrefs(next);
    applyDocumentPrefs(next);
    writeCachedPrefs(next);
    if (persist) void api('set_ui_prefs', [{ theme: next.theme, lang: next.lang }]);
  };

  const changeLang = async (lang: Lang, persist = true, base?: Prefs) => {
    const nextDict = await loadDict(lang);
    setDict(nextDict);
    commitPrefs({ ...(base ?? prefsRef.current), lang }, persist);
  };
  const prefsRef = useRef(prefs);
  prefsRef.current = prefs;

  const changeTheme = (theme: Theme) => commitPrefs({ ...prefsRef.current, theme }, true);

  // Cached prefs paint instantly; the backend copy (desktop_state.json) wins once loaded.
  useEffect(() => {
    let live = true;
    void api('get_ui_prefs').then((r) => {
      if (!live || r.ok === false) return;
      serverPrefsLoaded.current = true;
      const remote = migratePrefs(r.prefs as Record<string, unknown> | undefined);
      const merged: Prefs = { ...prefsRef.current, ...remote };
      if (merged.lang !== prefsRef.current.lang) void changeLang(merged.lang, false, merged);
      else if (merged.theme !== prefsRef.current.theme) commitPrefs(merged, false);
    });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => onAuthError(() => setExpired(true)), []);

  return (
    <I18nContext.Provider value={i18n}>
      <div class="app">
        <Sidebar route={route} prefs={prefs} onLang={(l) => void changeLang(l)} onTheme={changeTheme} />
        <TopBar route={route} />
        <div class="session-banner">
          {expired ? <Banner tone="danger" flat role="alert" title={t('session.expired')} /> : null}
        </div>
        <main class="main" id="main">
          <PageHost route={route} />
        </main>
      </div>
      <Toasts />
      <GuardModal pending={pending} />
    </I18nContext.Provider>
  );
}

/** Unsaved-changes prompt; its modal chunk loads only when first needed. */
function GuardModal({ pending }: { pending: RouteId | null }) {
  const [Modal, setModal] = useState<typeof ConfirmModalType | null>(null);
  useEffect(() => {
    if (pending && !Modal) void import('../components/Modal').then((m) => setModal(() => m.ConfirmModal));
  }, [pending, Modal]);
  return (
    <I18nContext.Consumer>
      {({ t }) => (Modal && pending ? (
        <Modal
          open
          title={t('common.unsavedTitle')}
          body={t('common.unsavedBody')}
          confirmLabel={t('common.discard')}
          cancelLabel={t('common.stay')}
          danger
          onConfirm={() => router().confirmPending()}
          onCancel={() => router().cancelPending()}
        />
      ) : null)}
    </I18nContext.Consumer>
  );
}

function PageHost({ route }: { route: RouteId }) {
  const [page, setPage] = useState<{ id: RouteId; Comp: ComponentType } | null>(() => {
    const Comp = getLoadedPage(route);
    return Comp ? { id: route, Comp } : null;
  });
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    setFailed(false);
    const Comp = getLoadedPage(route);
    if (Comp) {
      setPage({ id: route, Comp });
      return undefined;
    }
    preloadPage(route).then(
      (C) => { if (live) setPage({ id: route, Comp: C }); },
      () => { if (live) setFailed(true); },
    );
    return () => { live = false; };
  }, [route, attempt]);

  useLayoutEffect(() => {
    document.getElementById('main')?.scrollTo(0, 0);
  }, [route]);

  if (page && page.id === route) {
    const { Comp } = page;
    return <Comp key={route} />;
  }
  return (
    <div class="page">
      {failed ? <PageLoadError onRetry={() => setAttempt((n) => n + 1)} /> : <Skeleton lines={8} />}
    </div>
  );
}

function PageLoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <I18nContext.Consumer>
      {({ t }) => (
        <div class="panel-state" role="alert">
          <span class="text-danger">{t('common.loadFailed')}</span>
          <Button size="sm" onClick={onRetry}>{t('common.retry')}</Button>
        </div>
      )}
    </I18nContext.Consumer>
  );
}
