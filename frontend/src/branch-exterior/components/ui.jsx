export const Empty = ({ icon, children, bare, style }) => (
  <div className={`bx-empty${bare ? ' bare' : ''}`} style={style}>
    <div className="ic">{icon}</div>
    {children}
  </div>
);
export const Badge = ({ kind, value, text }) => <span className={`bx-badge ${kind}-${value}`}>{text ?? String(value).replace('_', ' ')}</span>;
