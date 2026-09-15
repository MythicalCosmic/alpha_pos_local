import type { Plan } from '../bridge/types';

// Shown only when the control center can't be reached. Prices are omitted on
// purpose: they're authoritative only from the control center.
export const FALLBACK_PLANS: readonly Plan[] = [
  { id: 'starter', name: 'Starter', descKey: 'lic.p1d', price: null, currency: 'UZS', period: 'mo', desc: '' },
  { id: 'standard', name: 'Standard', descKey: 'lic.p2d', price: null, currency: 'UZS', period: 'mo', desc: '' },
  { id: 'pro', name: 'Pro', descKey: 'lic.p3d', price: null, currency: 'UZS', period: 'mo', desc: '' },
];

type RawPlan = Record<string, unknown>;

/** Tolerate {plans:[…]}, {results:[…]}, {data:[…]} or a bare array. */
export function normalizePlans(data: unknown): Plan[] {
  if (!data) return [];
  const d = data as Record<string, unknown>;
  const arr: unknown[] = Array.isArray(data) ? data
    : Array.isArray(d.plans) ? d.plans
      : Array.isArray(d.results) ? d.results
        : Array.isArray(d.data) ? d.data : [];
  return arr.filter((p): p is RawPlan => !!p && typeof p === 'object').map((p, i) => {
    const id = p.id ?? p.plan_id ?? (p.code || p.slug || p.name || String(i));
    const name = p.name || p.title || p.label || p.display_name || String(id);
    const price = [p.price, p.price_uzs, p.monthly_price, p.amount].find((x) => x != null);
    const desc = p.description || p.desc || p.summary || (Array.isArray(p.features) ? p.features.join(' · ') : '');
    return {
      id: String(id), name: String(name), price,
      currency: String(p.currency || 'UZS'),
      period: String(p.period || p.interval || p.billing_period || 'mo'),
      desc: String(desc),
    };
  });
}

/** Compare the full trimmed plan name (multi-word plans must match). */
export function findCurrentPlan(plans: readonly Plan[], registered: boolean, planName: string | undefined): Plan | undefined {
  const current = registered ? String(planName || '').trim().toLowerCase() : '';
  if (!current) return undefined;
  return plans.find((p) => p.name.toLowerCase() === current || p.id.toLowerCase() === current);
}
