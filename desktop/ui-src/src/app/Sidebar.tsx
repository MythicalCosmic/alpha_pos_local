import { IconMonitor, IconMoon, IconSun } from '../components/icons';
import { IconButton, Segmented } from '../components/ui';
import { useUpdateStatus } from '../data/queries';
import { useT, type Lang } from '../i18n';
import type { Prefs, Theme } from '../lib/prefs';
import { hrefFor, navigate, type RouteId } from '../router/router';
import { preloadPage, ROUTES } from '../router/routes';

const LANG_OPTIONS = [
  { value: 'en' as const, label: 'EN', title: 'English' },
  { value: 'uz' as const, label: 'UZ', title: 'Oʻzbekcha' },
  { value: 'ru' as const, label: 'RU', title: 'Русский' },
];

const NEXT_THEME: Record<Theme, Theme> = { light: 'dark', dark: 'system', system: 'light' };
const THEME_KEY = { light: 'theme.light', dark: 'theme.dark', system: 'theme.system' } as const;

function Version() {
  const t = useT();
  const { data } = useUpdateStatus();
  const version = data && data.ok !== false ? data.version : undefined;
  return <div class="side-ver" title={version ? `${t('common.version')} ${version}` : undefined}>{version ? `v${version}` : ' '}</div>;
}

export function Sidebar({ route, prefs, onLang, onTheme }: {
  route: RouteId; prefs: Prefs; onLang: (lang: Lang) => void; onTheme: (theme: Theme) => void;
}) {
  const t = useT();
  const themeLabel = `${t('common.theme')}: ${t(THEME_KEY[prefs.theme])}`;
  return (
    <aside class="sidebar">
      <div class="brand">
        <img src="./AlphaPOS.png" alt="" width={24} height={24} />
        <span>Alpha POS</span>
      </div>
      <nav class="nav" aria-label={t('common.navigation')}>
        {ROUTES.map((r) => {
          const Icon = r.icon;
          const label = t(r.titleKey);
          return (
            <a
              key={r.id}
              href={hrefFor(r.id)}
              aria-current={r.id === route ? 'page' : undefined}
              title={label}
              onMouseEnter={() => void preloadPage(r.id).catch(() => {})}
              onFocus={() => void preloadPage(r.id).catch(() => {})}
              onClick={(e) => { e.preventDefault(); navigate(r.id); }}
            >
              <Icon size={17} />
              <span class="nav-label">{label}</span>
            </a>
          );
        })}
      </nav>
      <div class="side-foot">
        <div class="side-row">
          <Segmented options={LANG_OPTIONS} value={prefs.lang} onChange={onLang} label={t('common.language')} />
          <IconButton label={themeLabel} onClick={() => onTheme(NEXT_THEME[prefs.theme])}>
            {prefs.theme === 'light' ? <IconSun size={16} /> : prefs.theme === 'dark' ? <IconMoon size={16} /> : <IconMonitor size={16} />}
          </IconButton>
        </div>
        <Version />
      </div>
    </aside>
  );
}
