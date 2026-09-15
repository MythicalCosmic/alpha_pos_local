import type { ComponentChildren } from 'preact';
import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';

export interface VirtualListProps<T> {
  items: readonly T[];
  rowHeight: number;
  /** CSS height of the scroll viewport. */
  height: string;
  overscan?: number;
  label: string;
  renderRow: (item: T, index: number, style: string) => ComponentChildren;
}

/** Fixed-row-height windowing: only the visible slice (+overscan) is in the DOM. */
export function VirtualList<T>({ items, rowHeight, height, overscan = 6, label, renderRow }: VirtualListProps<T>) {
  const ref = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewport, setViewport] = useState(400);

  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return undefined;
    setViewport(node.clientHeight || 400);
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(() => setViewport(node.clientHeight || 400));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;
    let frame = 0;
    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        setScrollTop(node.scrollTop);
      });
    };
    node.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      node.removeEventListener('scroll', onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  const total = items.length * rowHeight;
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
  const end = Math.min(items.length, Math.ceil((scrollTop + viewport) / rowHeight) + overscan);
  const rows: ComponentChildren[] = [];
  for (let i = start; i < end; i++) rows.push(renderRow(items[i], i, `top:${i * rowHeight}px`));

  return (
    <div class="vlist" ref={ref} style={{ height }} role="listbox" aria-label={label} tabIndex={0}>
      <div class="vlist-inner" style={{ height: `${total}px` }}>{rows}</div>
    </div>
  );
}
