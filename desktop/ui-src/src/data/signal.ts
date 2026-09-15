import { useEffect, useState } from 'preact/hooks';

export interface Signal<T> {
  get(): T;
  set(value: T): void;
  subscribe(fn: (value: T) => void): () => void;
}

export function createSignal<T>(initial: T): Signal<T> {
  let value = initial;
  const listeners = new Set<(value: T) => void>();
  return {
    get: () => value,
    set(next) {
      if (Object.is(next, value)) return;
      value = next;
      listeners.forEach((fn) => fn(value));
    },
    subscribe(fn) {
      listeners.add(fn);
      return () => { listeners.delete(fn); };
    },
  };
}

export function useSignal<T>(signal: Signal<T>): T {
  const [value, setValue] = useState(signal.get);
  useEffect(() => {
    setValue(signal.get());
    return signal.subscribe((next) => setValue(() => next));
  }, [signal]);
  return value;
}
