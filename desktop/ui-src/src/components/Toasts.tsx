import { useEffect, useState } from 'preact/hooks';
import type { Tone } from '../lib/sync';

export interface ToastItem {
  id: number;
  message: string;
  tone: Tone;
}

const DURATION_MS = 3200;
let items: ToastItem[] = [];
let seq = 0;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((fn) => fn());

export function dismissToast(id: number): void {
  items = items.filter((x) => x.id !== id);
  emit();
}

export function toast(message: string, tone: Tone = 'info'): void {
  const id = ++seq;
  items = [...items.slice(-3), { id, message, tone }];
  emit();
  setTimeout(() => dismissToast(id), DURATION_MS);
}

export function Toasts() {
  const [list, setList] = useState(items);
  useEffect(() => {
    const sync = () => setList(items);
    listeners.add(sync);
    return () => { listeners.delete(sync); };
  }, []);
  return (
    <div class="toasts" role="status" aria-live="polite">
      {list.map((x) => (
        <div class="toast" key={x.id}>
          <span class={`dot ${x.tone}`} aria-hidden="true" />
          <span>{x.message}</span>
        </div>
      ))}
    </div>
  );
}
