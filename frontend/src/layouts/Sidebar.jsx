import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { ChevronRight, ScanEye } from 'lucide-react';
import { NAV_SECTIONS, formatBadge, isItemActive, openGroupIds, visibleSections } from './navConfig.js';

const ROW = 'relative flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-left';
const ACTIVE_BAR = 'before:absolute before:inset-y-2 before:left-0 before:w-[3px] before:rounded-r before:bg-accent';

const rowClass = ({ active, muted, collapsed, sub }) => [
  ROW,
  collapsed ? 'min-h-11 justify-center px-0' : '',
  sub ? 'py-1.5 font-normal' : '',
  active ? `bg-white/15 text-white ${ACTIVE_BAR}` : `${muted ? 'text-slate-400' : 'text-slate-300'} hover:bg-white/10 hover:text-white`,
].filter(Boolean).join(' ');

/** Collapsed: icon only, label kept for screen readers and shown as a tooltip. */
function Label({ children, collapsed }) {
  return <span className={collapsed ? 'sr-only' : 'min-w-0 flex-1 truncate'}>{children}</span>;
}

function Tag({ children, pink = false }) {
  return (
    <span className={`ml-auto shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
      pink ? 'bg-accent text-white' : 'border border-white/20 uppercase tracking-wide text-slate-400'
    }`}
    >
      {children}
    </span>
  );
}

function NavItem({ item, pathname, collapsed, muted, sub = false, badgeText, onNavigate }) {
  const { icon: Icon, label } = item;
  const title = collapsed ? label : undefined;
  const icon = Icon && <Icon className="h-[18px] w-[18px] shrink-0" aria-hidden />;

  if (item.soon) {
    return (
      <div aria-disabled="true" title={title} className={`${rowClass({ collapsed, muted })} cursor-default opacity-50 hover:bg-transparent hover:text-slate-300`}>
        {icon}
        <Label collapsed={collapsed}>{label}</Label>
        {!collapsed && <Tag>Soon</Tag>}
      </div>
    );
  }

  const active = isItemActive(item, pathname);
  return (
    <Link
      to={item.to}
      title={title}
      aria-current={active ? 'page' : undefined}
      onClick={onNavigate}
      className={rowClass({ active, muted, collapsed, sub })}
    >
      {icon}
      <Label collapsed={collapsed}>{label}</Label>
      {!collapsed && item.dev && <Tag>Dev</Tag>}
      {!collapsed && badgeText && <Tag pink>{badgeText}</Tag>}
    </Link>
  );
}

function NavGroup({ item, pathname, collapsed, muted, open, onToggle, badgeText, onNavigate }) {
  const { icon: Icon, label } = item;
  const panelId = `nav-group-${item.id}`;
  const active = isItemActive(item, pathname);
  const showOpen = open && !collapsed;
  return (
    <div>
      <button
        type="button"
        aria-expanded={showOpen}
        aria-controls={panelId}
        title={collapsed ? label : undefined}
        onClick={() => onToggle(item.id)}
        className={rowClass({ active: active && collapsed, muted, collapsed })}
      >
        {Icon && <Icon className="h-[18px] w-[18px] shrink-0" aria-hidden />}
        <Label collapsed={collapsed}>{label}</Label>
        {!collapsed && badgeText && <Tag pink>{badgeText}</Tag>}
        {!collapsed && (
          <ChevronRight
            className={`h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform motion-reduce:transition-none ${showOpen ? 'rotate-90' : ''}`}
            aria-hidden
          />
        )}
      </button>
      {!collapsed && (
        <div id={panelId} hidden={!showOpen} className="ml-5 mt-0.5 flex flex-col gap-0.5 border-l border-white/10 pl-2">
          {item.children.map((child) => (
            <NavItem key={child.id} item={child} sub pathname={pathname} collapsed={false} muted={muted} onNavigate={onNavigate} />
          ))}
        </div>
      )}
    </div>
  );
}

function Section({ label, collapsed }) {
  if (collapsed) return <hr className="mx-2 my-2 border-white/10" aria-hidden />;
  return label ? <p className="mt-4 px-3 text-[10.5px] font-semibold uppercase tracking-wider text-slate-400">{label}</p> : null;
}

function Brand({ collapsed }) {
  return (
    <div className={`mb-3 flex items-center gap-2.5 text-white ${collapsed ? 'justify-center' : 'px-2'}`}>
      <div className="grid h-9 w-9 shrink-0 place-items-center rounded-[10px] bg-gradient-to-br from-accent to-violet-500">
        <ScanEye className="h-5 w-5" aria-hidden />
      </div>
      <div className={collapsed ? 'sr-only' : 'min-w-0'}>
        <p className="text-[15px] font-semibold leading-tight">Fedbank Vision</p>
        <p className="text-[11px] text-slate-400">Security monitoring</p>
      </div>
    </div>
  );
}

/** Open groups: starts from `defaultOpen`/active route; manual toggles are remembered; navigating opens the owner group. */
function useOpenGroups(sections, pathname) {
  const [open, setOpen] = useState(() => new Set(openGroupIds(sections, pathname)));
  const activeKey = openGroupIds(sections, pathname).join('|');
  useEffect(() => {
    const active = sections.flatMap((s) => s.items).filter((i) => i.children && isItemActive(i, pathname)).map((i) => i.id);
    if (active.length) setOpen((prev) => (active.every((id) => prev.has(id)) ? prev : new Set([...prev, ...active])));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the route's owning groups only
  }, [activeKey]);
  const toggle = useCallback((id) => setOpen((prev) => {
    const next = new Set(prev);
    if (!next.delete(id)) next.add(id);
    return next;
  }), []);
  const show = useCallback((id) => setOpen((prev) => (prev.has(id) ? prev : new Set([...prev, id]))), []);
  return { open, toggle, show };
}

/**
 * @param {{
 *   collapsed?: boolean,
 *   devEnabled?: boolean,
 *   badges?: Record<string, number>,
 *   onNavigate?: () => void,
 *   onExpand?: () => void,
 * }} props
 * `onNavigate` fires only when a link is clicked (never for group toggles); `onExpand` expands a collapsed rail.
 */
export default function Sidebar({ collapsed = false, devEnabled = false, badges = {}, onNavigate, onExpand }) {
  const { pathname } = useLocation();
  const sections = useMemo(() => visibleSections(NAV_SECTIONS, { devEnabled }), [devEnabled]);
  const { open, toggle, show } = useOpenGroups(sections, pathname);

  const onGroup = (id) => {
    if (collapsed) {
      show(id);
      onExpand?.();
    } else {
      toggle(id);
    }
  };

  return (
    <nav aria-label="Main" className={`flex h-full flex-col gap-0.5 overflow-y-auto bg-navy ${collapsed ? 'p-3' : 'p-4'}`}>
      <Brand collapsed={collapsed} />
      {sections.map((section) => (
        <div key={section.label ?? 'top'} className="flex flex-col gap-0.5">
          <Section label={section.label} collapsed={collapsed && Boolean(section.label)} />
          {section.items.map((item) => {
            const badgeText = item.badge ? formatBadge(badges[item.badge]) : null;
            return item.children ? (
              <NavGroup
                key={item.id}
                item={item}
                pathname={pathname}
                collapsed={collapsed}
                muted={section.muted}
                open={open.has(item.id)}
                onToggle={onGroup}
                badgeText={badgeText}
                onNavigate={onNavigate}
              />
            ) : (
              <NavItem key={item.id} item={item} pathname={pathname} collapsed={collapsed} muted={section.muted} badgeText={badgeText} onNavigate={onNavigate} />
            );
          })}
        </div>
      ))}
    </nav>
  );
}
