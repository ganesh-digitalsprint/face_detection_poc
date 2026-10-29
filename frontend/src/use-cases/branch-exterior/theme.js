import { useSyncExternalStore } from 'react';

const KEY = 'bx-theme';
const subs = new Set();
let theme = 'light';
try { theme = localStorage.getItem(KEY) === 'dark' ? 'dark' : 'light'; } catch { /* ignore */ }

export const getTheme = () => theme;
export function toggleTheme() {
  theme = theme === 'dark' ? 'light' : 'dark';
  try { localStorage.setItem(KEY, theme); } catch { /* ignore */ }
  subs.forEach((f) => f());
}
export function useBxTheme() {
  return useSyncExternalStore((cb) => { subs.add(cb); return () => subs.delete(cb); }, getTheme);
}
