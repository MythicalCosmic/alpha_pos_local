import type { ComponentChildren, JSX } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { useT } from '../i18n';
import type { Tone } from '../lib/sync';
import { IconCheck, IconCopy, IconWarn } from './icons';
import { toast } from './Toasts';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'danger-solid';

export interface ButtonProps extends Omit<JSX.HTMLAttributes<HTMLButtonElement>, 'icon' | 'size'> {
  variant?: ButtonVariant;
  size?: 'sm' | 'md';
  icon?: ComponentChildren;
  loading?: boolean;
  disabled?: boolean;
  type?: 'button' | 'submit';
}

export function Button({ variant = 'secondary', size = 'md', icon, loading, children, class: cls, disabled, type = 'button', ...rest }: ButtonProps) {
  const className = ['btn', variant !== 'secondary' && `btn-${variant}`, size === 'sm' && 'btn-sm', cls].filter(Boolean).join(' ');
  return (
    <button type={type} class={className} disabled={disabled || loading} aria-busy={loading || undefined} {...rest}>
      {loading ? <span class="spinner" aria-hidden="true" /> : icon}
      {children}
    </button>
  );
}

export interface IconButtonProps extends Omit<JSX.HTMLAttributes<HTMLButtonElement>, 'label'> {
  label: string;
  disabled?: boolean;
}

export function IconButton({ label, children, class: cls, ...rest }: IconButtonProps) {
  return (
    <button type="button" class={cls ? `icon-btn ${cls}` : 'icon-btn'} aria-label={label} title={label} {...rest}>
      {children}
    </button>
  );
}

export interface CardProps {
  title?: ComponentChildren;
  actions?: ComponentChildren;
  children?: ComponentChildren;
  tone?: 'danger' | 'warn';
  class?: string;
  id?: string;
  labelledBy?: string;
}

export function Card({ title, actions, children, tone, class: cls, id }: CardProps) {
  const className = ['card', tone && `tone-${tone}`, cls].filter(Boolean).join(' ');
  return (
    <section class={className} id={id}>
      {(title || actions) && (
        <div class="card-head">
          {title ? <h2>{title}</h2> : <span style="flex:1" />}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Badge({ tone = 'muted', children }: { tone?: Tone; children: ComponentChildren }) {
  return <span class={`badge ${tone}`}>{children}</span>;
}

export function StatusDot({ tone = 'muted' }: { tone?: Tone }) {
  return <span class={`dot ${tone}`} aria-hidden="true" />;
}

export function Spinner({ label }: { label?: string }) {
  return <span class="spinner" role={label ? 'status' : undefined} aria-label={label} aria-hidden={label ? undefined : 'true'} />;
}

export interface SwitchProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabled?: boolean;
}

export function Switch({ checked, onChange, label, disabled }: SwitchProps) {
  return (
    <button
      type="button" role="switch" class="switch" aria-checked={checked} aria-label={label}
      disabled={disabled} onClick={() => onChange(!checked)}
    />
  );
}

export interface SegmentedOption<V extends string> {
  value: V;
  label: ComponentChildren;
  title?: string;
}

export function Segmented<V extends string>({ options, value, onChange, label, disabled }: {
  options: readonly SegmentedOption<V>[];
  value: V | undefined;
  onChange: (value: V) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <div class="seg" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value} type="button" role="radio" aria-checked={o.value === value}
          title={o.title} aria-label={o.title} disabled={disabled}
          onClick={() => { if (o.value !== value) onChange(o.value); }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, hint, children, htmlFor }: { label: ComponentChildren; hint?: ComponentChildren; children: ComponentChildren; htmlFor?: string }) {
  return (
    <div class="field">
      <label class="field-label" for={htmlFor}>{label}</label>
      {children}
      {hint ? <span class="field-hint">{hint}</span> : null}
    </div>
  );
}

export function KV({ label, children, mono, dim, copy }: { label: ComponentChildren; children?: ComponentChildren; mono?: boolean; dim?: boolean; copy?: string }) {
  return (
    <div class="kv-row">
      <span class="kv-l">{label}</span>
      <span class={`kv-v${mono ? ' mono' : ''}${dim ? ' dim' : ''}`}>
        {children}
        {copy ? <CopyButton text={copy} label={typeof label === 'string' ? label : undefined} /> : null}
      </span>
    </div>
  );
}

export function KeyValue({ children }: { children: ComponentChildren }) {
  return <div class="kv">{children}</div>;
}

export function CopyButton({ text, label }: { text: string; label?: string }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return undefined;
    const id = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(id);
  }, [copied]);
  const name = label ? `${t('common.copy')}: ${label}` : t('common.copy');
  return (
    <IconButton
      label={name}
      class={copied ? 'ok' : undefined}
      onClick={() => {
        try {
          void navigator.clipboard?.writeText(text);
        } catch {
          /* clipboard unavailable */
        }
        setCopied(true);
        toast(t('common.copied'), 'ok');
      }}
    >
      {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
    </IconButton>
  );
}

/** Two-step inline confirm for low-risk destructive actions. */
export function ConfirmButton({ label, onConfirm, variant = 'danger', icon, loading, disabled }: {
  label: string; onConfirm: () => void; variant?: ButtonVariant; icon?: ComponentChildren; loading?: boolean; disabled?: boolean;
}) {
  const t = useT();
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return undefined;
    const id = setTimeout(() => setArmed(false), 3000);
    return () => clearTimeout(id);
  }, [armed]);
  return (
    <Button
      variant={armed ? 'danger-solid' : variant} icon={icon} loading={loading} disabled={disabled}
      onClick={() => {
        if (armed) {
          setArmed(false);
          onConfirm();
        } else setArmed(true);
      }}
    >
      {armed ? t('common.confirm') : label}
    </Button>
  );
}

export function Banner({ tone = 'info', title, children, actions, flat, role }: {
  tone?: 'info' | 'warn' | 'danger'; title?: ComponentChildren; children?: ComponentChildren;
  actions?: ComponentChildren; flat?: boolean; role?: 'alert' | 'status';
}) {
  return (
    <div class={`banner ${tone}${flat ? ' flat' : ''}`} role={role}>
      <IconWarn size={16} />
      <div class="banner-body">
        {title ? <strong>{title}</strong> : null}
        {children ? <div class={title ? 'small' : undefined}>{children}</div> : null}
      </div>
      {actions}
    </div>
  );
}

export function EmptyState({ children }: { children: ComponentChildren }) {
  return <div class="empty">{children}</div>;
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div class="skeleton" aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => <i key={i} />)}
    </div>
  );
}

export function StaleBar({ onRetry }: { onRetry?: () => void }) {
  const t = useT();
  return (
    <div class="stale" role="status">
      <IconWarn size={14} />
      <span>{t('common.stale')}</span>
      {onRetry ? <Button size="sm" variant="ghost" onClick={onRetry}>{t('common.retry')}</Button> : null}
    </div>
  );
}

export function Meter({ pct, label }: { pct: number; label: string }) {
  return (
    <div class="meter" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
      <i style={{ width: `${pct}%` }} />
    </div>
  );
}
