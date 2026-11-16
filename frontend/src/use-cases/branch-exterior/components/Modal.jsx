import { useEffect, useRef } from 'react';

/** Same dialog as the original: backdrop click closes, header with ×, body, optional footer. */
export default function Modal({ title, onClose, footer, children, maxWidth }) {
  const dialogRef = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); onCloseRef.current?.(); } };
    const previousOverflow = document.body.style.overflow;
    const previouslyFocused = document.activeElement;
    document.body.style.overflow = 'hidden';
    dialogRef.current?.querySelector('button, a[href], input, textarea, [tabindex]:not([tabindex="-1"])')?.focus();
    document.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('keydown', onKey, true);
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus?.();
    };
  }, []);
  const trapFocus = (event) => {
    if (event.key !== 'Tab') return;
    const controls = [...(dialogRef.current?.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])') || [])];
    if (!controls.length) { event.preventDefault(); return; }
    const first = controls[0]; const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };
  return (
    <div className="bx-backdrop bx-page" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.(); }}>
      <div ref={dialogRef} className="bx-modal" role="dialog" aria-modal="true" aria-label={title} onKeyDown={trapFocus} style={maxWidth ? { maxWidth } : undefined}>
        <div className="bx-modal-header">
          <h3>{title}</h3>
          <button type="button" className="bx-icon-btn" aria-label="Close" onClick={onClose}>&times;</button>
        </div>
        <div className="bx-modal-body">{children}</div>
        {footer && <div className="bx-modal-footer">{footer}</div>}
      </div>
    </div>
  );
}
