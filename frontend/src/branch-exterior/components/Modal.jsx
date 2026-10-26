import { useEffect } from 'react';

/** Same dialog as the original: backdrop click closes, header with ×, body, optional footer. */
export default function Modal({ title, onClose, footer, children, maxWidth }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose?.(); } };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [onClose]);
  return (
    <div className="bx-backdrop bx-page" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.(); }}>
      <div className="bx-modal" role="dialog" aria-modal="true" style={maxWidth ? { maxWidth } : undefined}>
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
