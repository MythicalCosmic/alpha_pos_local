import type { ComponentChildren } from 'preact';
import type { BackendResult } from '../bridge/transport';
import type { QueryResult } from '../data/useQuery';
import { useT } from '../i18n';
import { Button, EmptyState, Skeleton, Spinner, StaleBar } from './ui';

export interface QueryBoundaryProps<T extends BackendResult> {
  q: QueryResult<T>;
  skeleton?: number;
  empty?: (data: T) => boolean;
  emptyText?: ComponentChildren;
  children: (data: T) => ComponentChildren;
}

/**
 * no data + loading → skeleton; gated query while Django boots → "Preparing
 * database…"; no data + error → error panel with Retry; stale data → content
 * plus StaleBar; empty → EmptyState.
 */
export function QueryBoundary<T extends BackendResult>({ q, skeleton = 3, empty, emptyText, children }: QueryBoundaryProps<T>) {
  const t = useT();
  if (q.data === undefined) {
    if (q.preparing) {
      return (
        <div class="panel-state" role="status">
          <Spinner />
          <span>{t('phase.booting')}</span>
        </div>
      );
    }
    if (q.status === 'error') {
      const message = typeof q.error?.error === 'string' && q.error.error ? q.error.error : '';
      return (
        <div class="panel-state" role="alert">
          <span class="text-danger wrap">{t('common.loadFailed')}{message ? `: ${message}` : ''}</span>
          <Button size="sm" onClick={() => void q.refetch()}>{t('common.retry')}</Button>
        </div>
      );
    }
    return <Skeleton lines={skeleton} />;
  }
  if (empty?.(q.data)) return <EmptyState>{emptyText ?? t('common.empty')}</EmptyState>;
  return (
    <>
      {q.stale ? <StaleBar onRetry={() => void q.refetch()} /> : null}
      {children(q.data)}
    </>
  );
}
