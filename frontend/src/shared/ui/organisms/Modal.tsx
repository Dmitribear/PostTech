import { t, tx } from '@/shared/lib/i18n';
import { useEffect, useRef, type ReactNode } from 'react';
import { Icon } from '../atoms/Icon';
export function Modal({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const node = dialog.current;
    node?.showModal();
    const before = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      node?.close();
      document.body.style.overflow = before;
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className={`modal ${wide ? 'modal-wide' : ''}`}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        close.current();
      }}
      onClick={(e) => {
        if (e.target === dialog.current) close.current();
      }}
    >
      <div className="modal-inner">
        <div className="modal-heading">
          <h2>{tx(title)}</h2>
          <button className="icon-btn" aria-label={t('Закрыть')} onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>
        {tx(children)}
      </div>
    </dialog>
  );
}
