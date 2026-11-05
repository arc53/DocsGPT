import { act, Suspense, use } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import {
  MemoryRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
} from 'react-router-dom';

vi.mock('./useSectionResolver', () => ({
  useSectionResolver: () => () => null,
}));

import { SidebarLevelProvider, useSidebarLevel } from './SidebarLevelProvider';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let goTo: (to: string) => void = () => {};

function Probe() {
  const { pending, goToLevel } = useSidebarLevel();
  goTo = goToLevel;
  return (
    <div data-testid="probe">
      {`${useLocation().pathname}|${pending?.pathname ?? ''}`}
    </div>
  );
}

let release: () => void = () => {};
let slowPage: Promise<void>;

function SlowPage() {
  use(slowPage);
  return <p>slow</p>;
}

describe('SidebarLevelProvider', () => {
  let container: HTMLDivElement;
  let root: Root;

  const probe = () =>
    container.querySelector('[data-testid="probe"]')?.textContent;

  beforeEach(() => {
    slowPage = new Promise<void>((resolve) => {
      release = resolve;
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    act(() => {
      root.render(
        <MemoryRouter initialEntries={['/']}>
          <SidebarLevelProvider>
            <Probe />
            <Suspense fallback={null}>
              <Routes>
                <Route path="/" element={<p>home</p>} />
                <Route path="/slow" element={<SlowPage />} />
                <Route path="/moved" element={<Navigate to="/" replace />} />
              </Routes>
            </Suspense>
          </SidebarLevelProvider>
        </MemoryRouter>,
      );
    });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  // The sidebar used to give up on a level after a fixed 600ms. A page that
  // took longer to render made it slide in, slide back out when the timer
  // fired, then slide in again once the route finally committed.
  it('holds the level for as long as the navigation is still rendering', async () => {
    await act(async () => goTo('/slow'));
    expect(probe()).toBe('/|/slow');

    await act(() => new Promise((resolve) => setTimeout(resolve, 800)));
    expect(probe()).toBe('/|/slow');

    await act(async () => release());
    expect(probe()).toBe('/slow|');
  });

  it('lets go of the level when the navigation lands somewhere else', async () => {
    await act(async () => goTo('/moved'));
    expect(probe()).toBe('/|');
  });
});
