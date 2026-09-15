import type { ComponentType, FunctionComponent } from 'preact';
import {
  IconDashboard, IconDownload, IconFlask, IconLicense, IconLogs, IconReceipt, IconSend, IconSliders,
  type IconProps,
} from '../components/icons';
import type { I18nKey } from '../i18n';
import type { RouteId } from './router';

type PageModule = { default: ComponentType };

export interface RouteDef {
  id: RouteId;
  titleKey: I18nKey;
  icon: FunctionComponent<IconProps>;
  load: () => Promise<PageModule>;
}

export const ROUTES: readonly RouteDef[] = [
  { id: 'dashboard', titleKey: 'nav.dashboard', icon: IconDashboard, load: () => import('../pages/Dashboard') },
  { id: 'license', titleKey: 'nav.license', icon: IconLicense, load: () => import('../pages/License') },
  { id: 'local-audit', titleKey: 'nav.localAudit', icon: IconSend, load: () => import('../pages/LocalAudit') },
  { id: 'config', titleKey: 'nav.config', icon: IconSliders, load: () => import('../pages/Config') },
  { id: 'tests', titleKey: 'nav.tests', icon: IconFlask, load: () => import('../pages/Tests') },
  { id: 'fiscal', titleKey: 'nav.fiscal', icon: IconReceipt, load: () => import('../pages/Fiscal') },
  { id: 'logs', titleKey: 'nav.logs', icon: IconLogs, load: () => import('../pages/Logs') },
  { id: 'updates', titleKey: 'nav.updates', icon: IconDownload, load: () => import('../pages/Updates') },
];

export const ROUTE_MAP = Object.fromEntries(ROUTES.map((r) => [r.id, r])) as Record<RouteId, RouteDef>;

const loaded = new Map<RouteId, ComponentType>();
const loading = new Map<RouteId, Promise<ComponentType>>();

export function getLoadedPage(id: RouteId): ComponentType | undefined {
  return loaded.get(id);
}

/** Fetch a page chunk once; called on nav hover/focus and on navigation. */
export function preloadPage(id: RouteId): Promise<ComponentType> {
  const hit = loaded.get(id);
  if (hit) return Promise.resolve(hit);
  let pending = loading.get(id);
  if (!pending) {
    pending = ROUTE_MAP[id].load().then(
      (mod) => {
        loaded.set(id, mod.default);
        loading.delete(id);
        return mod.default;
      },
      (error) => {
        loading.delete(id);
        throw error;
      },
    );
    loading.set(id, pending);
  }
  return pending;
}
