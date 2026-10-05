import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, NavLink } from 'react-router-dom';

import { Button } from '../components/ui/button';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

// Navigation.tsx renders its sidebar rows as
// <Button variant="sidebar-item" asChild><NavLink end /></Button>; the
// variant keys its selected fill on the aria-current NavLink sets.
function renderRow(path: string) {
  act(() => {
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <Button variant="sidebar-item" asChild className="mx-4 mt-2 flex">
          <NavLink to="/agents/manage" end>
            Manage agents
          </NavLink>
        </Button>
      </MemoryRouter>,
    );
  });
  return container.querySelector('a') as HTMLAnchorElement;
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe('sidebar nav row', () => {
  it('is marked current on the exact route', () => {
    const link = renderRow('/agents/manage');
    expect(link.getAttribute('aria-current')).toBe('page');
    expect(link.dataset.variant).toBe('sidebar-item');
    expect(link.className).toContain('aria-[current=page]:bg-sidebar-accent');
    expect(link.className).toContain('mx-4');
    expect(link.classList.contains('inline-flex')).toBe(false);
  });

  it('is not current on a nested route, because of end', () => {
    const link = renderRow('/agents/manage/abc');
    expect(link.hasAttribute('aria-current')).toBe(false);
  });
});
