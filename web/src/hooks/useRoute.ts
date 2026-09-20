// Tiny history-based router: two routes, no dependency.
import { useCallback, useEffect, useState } from 'react';

export type Route = { name: 'home' } | { name: 'job'; jobId: string } | { name: 'notfound'; path: string };

export function parseRoute(pathname: string): Route {
  const clean = pathname.replace(/\/+$/, '') || '/';
  if (clean === '/') return { name: 'home' };
  const m = clean.match(/^\/jobs\/([^/]+)$/);
  if (m) return { name: 'job', jobId: decodeURIComponent(m[1]) };
  return { name: 'notfound', path: clean };
}

/** Keeps ?fixture=1 across navigations so fixture mode survives a click. */
export function href(path: string): string {
  const q = new URLSearchParams(window.location.search);
  return q.get('fixture') === '1' ? `${path}?fixture=1` : path;
}

export function useRoute(): [Route, (path: string) => void] {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.pathname));
  useEffect(() => {
    const onPop = () => setRoute(parseRoute(window.location.pathname));
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);
  const navigate = useCallback((path: string) => {
    window.history.pushState(null, '', href(path));
    setRoute(parseRoute(path));
    window.scrollTo(0, 0);
  }, []);
  return [route, navigate];
}
