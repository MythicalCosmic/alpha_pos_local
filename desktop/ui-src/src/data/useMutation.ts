import { useCallback, useEffect, useRef, useState } from 'preact/hooks';
import { api, type MethodName, type ResultOf } from '../bridge/methods';
import { store } from './store';

export interface MutationOptions {
  invalidate?: string[];
}

export interface Mutation<M extends MethodName> {
  run: (...args: unknown[]) => Promise<ResultOf<M>>;
  pending: boolean;
}

/** Fire a bridge write; tracks pending state and refreshes dependent queries. */
export function useMutation<M extends MethodName>(method: M, options: MutationOptions = {}): Mutation<M> {
  const [pending, setPending] = useState(false);
  const mounted = useRef(true);
  const invalidate = useRef(options.invalidate);
  invalidate.current = options.invalidate;
  useEffect(() => () => { mounted.current = false; }, []);
  const run = useCallback(async (...args: unknown[]) => {
    setPending(true);
    try {
      return await api(method, args);
    } finally {
      if (mounted.current) setPending(false);
      if (invalidate.current?.length) store.invalidate(invalidate.current);
    }
  }, [method]);
  return { run, pending };
}
