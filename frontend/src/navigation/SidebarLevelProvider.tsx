import {
  createContext,
  startTransition,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import type { Section } from './sections';
import { useSectionResolver } from './useSectionResolver';

type PendingLevel = { pathname: string; section: Section | null };

type SidebarLevelValue = {
  /** The level the sidebar should show, ahead of the route when moving. */
  pending: PendingLevel | null;
  /** Navigate in a way the sidebar can animate immediately. */
  goToLevel: (to: string) => void;
};

const SidebarLevelContext = createContext<SidebarLevelValue>({
  pending: null,
  goToLevel: () => {},
});

/**
 * Lets the sidebar change level on the click rather than on the commit.
 *
 * Mounting a section's page is expensive — measured at a single ~170ms
 * blocking frame in a production build — and the sidebar's own class change
 * used to ride along in that same commit. The panels therefore only began
 * moving once the new page had rendered: a pause, and then a slide the user
 * had stopped expecting.
 *
 * So the two updates are split by priority. The level lands as an urgent
 * update that touches nothing but the sidebar, so React can commit and paint
 * it straight away and the transition starts on time; the route change goes
 * through `startTransition`, which renders the page at low priority and
 * yields between slices instead of blocking that paint. The target's section
 * is resolved up front so the incoming panel slides in with its content
 * already in place rather than arriving empty.
 */
export function SidebarLevelProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const resolve = useSectionResolver();
  const [pending, setPending] = useState<PendingLevel | null>(null);

  const goToLevel = useCallback(
    (to: string) => {
      const pathname = to.split('?')[0];
      setPending({ pathname, section: resolve(pathname) });
      startTransition(() => navigate(to));
    },
    [navigate, resolve],
  );

  // Hand back to the route once it catches up, and never hold the sidebar
  // ahead of it for long: a navigation can be refused (an unsaved-changes
  // guard) or land somewhere else entirely, and a level that never resolved
  // would leave the sidebar showing a section the user is not in.
  useEffect(() => {
    if (!pending) return;
    if (pending.pathname === location.pathname) {
      setPending(null);
      return;
    }
    const timer = setTimeout(() => setPending(null), 600);
    return () => clearTimeout(timer);
  }, [pending, location.pathname]);

  return (
    <SidebarLevelContext.Provider value={{ pending, goToLevel }}>
      {children}
    </SidebarLevelContext.Provider>
  );
}

export const useSidebarLevel = () => useContext(SidebarLevelContext);
