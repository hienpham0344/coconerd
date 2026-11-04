import { useEffect, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';
export function Dialog({ title, onClose, children, wide = false }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    const previous = document.activeElement as HTMLElement;
    const scroll = { left: window.scrollX, top: window.scrollY, behavior: 'instant' as const };
    const old = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.showModal();
    window.scrollTo(scroll);
    return () => {
      dialog.close(); document.body.style.overflow = old;
      previous?.focus({ preventScroll: true });
      window.scrollTo(scroll);
    };
  }, []);
  return <dialog ref={ref} className={`dialog ${wide ? 'dialog-wide' : ''}`} aria-label={title} onCancel={e => { e.preventDefault(); onClose(); }} onClick={e => { if (e.target === ref.current) onClose(); }}><div className="dialog-inner"><div className="dialog-top"><span className="eyebrow">{title}</span><button className="icon-button" onClick={onClose} aria-label="Close"><X size={20} /></button></div>{children}</div></dialog>;
}
