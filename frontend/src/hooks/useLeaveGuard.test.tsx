import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes, Link } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { useLeaveGuard } from './useLeaveGuard';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('useLeaveGuard', () => {
  let container: HTMLDivElement;
  let root: Root;
  const close = vi.fn();

  const beforeLeave = vi.fn();
  function Builder({ dirty }: { dirty: boolean }) {
    const { onNavigate, leaveTo, dialog } = useLeaveGuard(dirty);
    return (
      <>
        <Link to="/settings/tools" onClick={onNavigate(close)}>
          go
        </Link>
        <button type="button" onClick={() => leaveTo('/settings/connectors')}>
          browse
        </button>
        <button
          type="button"
          onClick={() => leaveTo('/settings/connectors', { beforeLeave })}
        >
          chat
        </button>
        {dialog}
      </>
    );
  }

  const render = (dirty: boolean) =>
    act(async () =>
      root.render(
        <MemoryRouter initialEntries={['/agents/new']}>
          <Routes>
            <Route path="/agents/new" element={<Builder dirty={dirty} />} />
            <Route path="/settings/tools" element={<p>tools page</p>} />
            <Route
              path="/settings/connectors"
              element={<p>connectors page</p>}
            />
          </Routes>
        </MemoryRouter>,
      ),
    );

  beforeEach(() => {
    close.mockClear();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const link = () => container.querySelector('a')!;
  const dialog = () => document.querySelector('[role="dialog"]');
  const dialogButton = (label: string) =>
    Array.from(dialog()!.querySelectorAll('button')).find(
      (b) => b.textContent === label,
    )!;

  it('lets a link go when nothing is unsaved', async () => {
    await render(false);
    await act(async () => link().click());
    expect(close).toHaveBeenCalled();
    expect(container.textContent).toBe('tools page');
  });

  it('asks first when something is unsaved, and leaves on Leave', async () => {
    await render(true);
    await act(async () => link().click());
    // The picker closes either way; the page stays until the reader says.
    expect(close).toHaveBeenCalled();
    expect(container.textContent).toContain('go');
    expect(dialog()!.textContent).toContain('agents.form.leave.title');
    expect(dialog()!.textContent).toContain('agents.form.leave.description');
    await act(async () => dialogButton('agents.form.leave.submit').click());
    expect(container.textContent).toBe('tools page');
  });

  it('stays on Cancel', async () => {
    await render(true);
    await act(async () => link().click());
    await act(async () => dialogButton('cancel').click());
    expect(dialog()).toBeNull();
    expect(container.textContent).toContain('go');
  });

  // A new tab leaves the builder where it is, so there is nothing to lose.
  it.each([
    ['Cmd', { metaKey: true }],
    ['Ctrl', { ctrlKey: true }],
    ['Shift', { shiftKey: true }],
    ['middle', { button: 1 }],
  ])('lets a %s click open its new tab without asking', async (_, init) => {
    await render(true);
    const click = new MouseEvent('click', {
      bubbles: true,
      cancelable: true,
      ...init,
    });
    let prevented: boolean | null = null;
    const watch = (event: Event) => {
      prevented = event.defaultPrevented;
    };
    // Read after React's handler, which runs at the root.
    document.addEventListener('click', watch);
    await act(async () => link().dispatchEvent(click));
    document.removeEventListener('click', watch);
    expect(dialog()).toBeNull();
    expect(container.textContent).toContain('go');
    // React Router's Link prevents a plain click itself; for a modified one
    // the browser opens the tab, so nothing may prevent it.
    expect(prevented).toBe(false);
  });

  // "Try in chat" clears the chat's selection: only if the reader leaves.
  it('runs beforeLeave only once leaving is allowed', async () => {
    beforeLeave.mockClear();
    const chat = () =>
      Array.from(container.querySelectorAll('button')).find(
        (b) => b.textContent === 'chat',
      )!;
    await render(true);
    await act(async () => chat().click());
    expect(beforeLeave).not.toHaveBeenCalled();
    await act(async () => dialogButton('cancel').click());
    expect(beforeLeave).not.toHaveBeenCalled();
    await act(async () => chat().click());
    await act(async () => dialogButton('agents.form.leave.submit').click());
    expect(beforeLeave).toHaveBeenCalledTimes(1);
    expect(container.textContent).toBe('connectors page');
  });

  it('runs beforeLeave at once when nothing is unsaved', async () => {
    beforeLeave.mockClear();
    await render(false);
    await act(async () =>
      Array.from(container.querySelectorAll('button'))
        .find((b) => b.textContent === 'chat')!
        .click(),
    );
    expect(beforeLeave).toHaveBeenCalledTimes(1);
    expect(container.textContent).toBe('connectors page');
  });

  it('guards a programmatic exit too', async () => {
    await render(true);
    await act(async () =>
      Array.from(container.querySelectorAll('button'))
        .find((b) => b.textContent === 'browse')!
        .click(),
    );
    await act(async () => dialogButton('agents.form.leave.submit').click());
    expect(container.textContent).toBe('connectors page');
  });
  // A reload, a closed tab or a typed URL leaves too: the browser's own
  // prompt asks while something is unsaved, and only then.
  const unload = () => {
    const event = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  };

  it('asks the browser to confirm an unload while something is unsaved', async () => {
    await render(true);
    expect(unload()).toBe(true);
  });

  it('lets an unload go when nothing is unsaved', async () => {
    await render(false);
    expect(unload()).toBe(false);
  });

  it('stops asking on unload once the work is saved', async () => {
    await render(true);
    expect(unload()).toBe(true);
    await render(false);
    expect(unload()).toBe(false);
  });

  it('stops asking on unload once the builder unmounts', async () => {
    await render(true);
    await act(async () => root.unmount());
    expect(unload()).toBe(false);
    root = createRoot(container);
  });
});
