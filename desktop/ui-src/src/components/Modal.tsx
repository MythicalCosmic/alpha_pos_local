import type { ComponentChildren } from 'preact';
import { useEffect, useId, useRef } from 'preact/hooks';
import { Button } from './ui';

export function Modal({ open, title, children, actions, onClose }: {
  open: boolean;
  title: ComponentChildren;
  children?: ComponentChildren;
  actions?: ComponentChildren;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!open) return undefined;
    const previous = document.activeElement as HTMLElement | null;
    const node = ref.current;
    const buttons = node?.querySelectorAll<HTMLElement>('button');
    buttons?.[0]?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeRef.current();
      } else if (event.key === 'Tab' && node) {
        const focusable = Array.from(node.querySelectorAll<HTMLElement>('button, input, select, textarea, a[href]'))
          .filter((el) => !el.hasAttribute('disabled'));
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      previous?.focus?.();
    };
  }, [open]);

  if (!open) return null;
  return (
    <div class="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) closeRef.current(); }}>
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby={titleId} ref={ref}>
        <h2 id={titleId}>{title}</h2>
        {children ? <div class="muted wrap">{children}</div> : null}
        {actions ? <div class="modal-actions">{actions}</div> : null}
      </div>
    </div>
  );
}

export function ConfirmModal({ open, title, body, confirmLabel, cancelLabel, danger, onConfirm, onCancel }: {
  open: boolean;
  title: ComponentChildren;
  body?: ComponentChildren;
  confirmLabel: string;
  cancelLabel: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal
      open={open} title={title} onClose={onCancel}
      actions={(
        <>
          <Button onClick={onCancel}>{cancelLabel}</Button>
          <Button variant={danger ? 'danger-solid' : 'primary'} onClick={onConfirm}>{confirmLabel}</Button>
        </>
      )}
    >
      {body}
    </Modal>
  );
}
