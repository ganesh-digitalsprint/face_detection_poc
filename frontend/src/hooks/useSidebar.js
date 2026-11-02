import { useCallback, useEffect, useState } from 'react';

const STORAGE_KEY = 'sidebar:collapsed';
const DESKTOP_QUERY = '(min-width: 1024px)'; // Tailwind `lg`

function readCollapsed() {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'true';
  } catch {
    return false;
  }
}

function writeCollapsed(value) {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(value));
  } catch {
    /* storage unavailable: the preference just isn't remembered */
  }
}

function matchesDesktop() {
  return typeof window !== 'undefined' && window.matchMedia(DESKTOP_QUERY).matches;
}

/**
 * Sidebar UI state only. Desktop: persisted expanded/collapsed rail.
 * Below `lg`: an overlay drawer that is closed by default and never persisted.
 */
export default function useSidebar() {
  const [isDesktop, setIsDesktop] = useState(matchesDesktop);
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    const media = window.matchMedia(DESKTOP_QUERY);
    const onChange = (event) => {
      setIsDesktop(event.matches);
      if (event.matches) setDrawerOpen(false);
    };
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, []);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      writeCollapsed(next);
      return next;
    });
  }, []);

  const toggle = useCallback(() => {
    if (matchesDesktop()) toggleCollapsed();
    else setDrawerOpen((open) => !open);
  }, [toggleCollapsed]);

  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  // On desktop "expanded" means the rail is wide; on mobile it means the drawer is open.
  const expanded = isDesktop ? !collapsed : drawerOpen;

  return { isDesktop, collapsed, drawerOpen, expanded, toggle, toggleCollapsed, closeDrawer };
}
