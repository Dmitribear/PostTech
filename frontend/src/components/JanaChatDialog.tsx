import { lazy, Suspense, useEffect, useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { t } from '../lib/i18n';
import { LoadingState } from './ui';

const Jana = lazy(() => import('../pages/Jana'));

/** Keep the shared chat mounted while hidden so drafts and in-flight replies survive. */
export function JanaChatDialog({ open, onClose, launcher }: {
  open: boolean; onClose: () => void; launcher: RefObject<HTMLButtonElement | null>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [visited, setVisited] = useState(false);
  useLayoutEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (open) { setVisited(true); if (!node.open) node.showModal(); }
    else if (node.open) { node.close(); launcher.current?.focus({ preventScroll: true }); }
  }, [open, launcher]);
  useEffect(() => () => { dialog.current?.close(); }, []);
  return <dialog ref={dialog} id="jana-global-chat" className="jana-chat-dialog" aria-label={t('Чат с AI Jana')} aria-modal="true"
    onKeyDown={event => {
      const node = dialog.current;
      if (event.key !== 'Tab' || !node || (event.target as Element).closest('dialog') !== node) return;
      const items = Array.from(node.querySelectorAll<HTMLElement>('button:not([disabled]),a[href],input:not([disabled]),textarea:not([disabled]),select:not([disabled]),summary,[tabindex]:not([tabindex="-1"])')).filter(item => item.getClientRects().length && item.closest('dialog') === node);
      const first = items[0], last = items.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }}
    onCancel={event => { if (event.target !== dialog.current) return; event.preventDefault(); onClose(); }}
    onClick={event => {
      if (event.target === dialog.current) { onClose(); return; }
      const link = (event.target as Element).closest<HTMLAnchorElement>('a[href]');
      if (link && !link.target && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && new URL(link.href).origin === window.location.origin) onClose();
    }}>
    {visited && <Suspense fallback={<div className="jana-widget-loading"><LoadingState /></div>}>
      <Jana embedded active={open} onClose={onClose} />
    </Suspense>}
  </dialog>;
}
