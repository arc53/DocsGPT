import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const media = { isMobile: true, isDesktop: false };
vi.mock('../hooks', () => ({
  useMediaQuery: () => media,
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import ConfirmationModal from './ConfirmationModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe('ConfirmationModal', () => {
  it('stays a centred dialog on phones, where Modal defaults to a sheet', async () => {
    await act(async () =>
      root.render(
        <ConfirmationModal
          message="Delete this agent?"
          modalState="ACTIVE"
          setModalState={() => undefined}
          submitLabel="Delete"
          handleSubmit={() => undefined}
        />,
      ),
    );
    const content = document.querySelector<HTMLElement>(
      '[data-slot="modal-content"]',
    )!;
    expect(content).not.toBeNull();
    expect(content.hasAttribute('data-mobile-sheet')).toBe(false);
  });
});

describe('ConfirmationModal async submit', () => {
  const submitButton = () =>
    Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent === 'Delete',
    )!;

  const deferred = () => {
    let resolve!: () => void;
    let reject!: (e: unknown) => void;
    const promise = new Promise<void>((res, rej) => {
      resolve = res;
      reject = rej;
    });
    return { promise, resolve, reject };
  };

  const renderModal = async (
    handleSubmit: () => void | Promise<unknown>,
    setModalState = vi.fn(),
    extra: { error?: string; children?: React.ReactNode } = {},
  ) => {
    await act(async () =>
      root.render(
        <ConfirmationModal
          message="Delete this agent?"
          modalState="ACTIVE"
          setModalState={setModalState}
          submitLabel="Delete"
          handleSubmit={handleSubmit}
          error={extra.error}
        >
          {extra.children}
        </ConfirmationModal>,
      ),
    );
    return setModalState;
  };

  it('closes at once after a sync submit, as before', async () => {
    const handleSubmit = vi.fn();
    const setModalState = await renderModal(handleSubmit);
    await act(async () => submitButton().click());
    expect(handleSubmit).toHaveBeenCalledTimes(1);
    expect(setModalState).toHaveBeenCalledWith('INACTIVE');
  });

  it('stays open with a pending submit until the promise resolves', async () => {
    const request = deferred();
    const handleSubmit = vi.fn(() => request.promise);
    const setModalState = await renderModal(handleSubmit);
    await act(async () => submitButton().click());
    expect(setModalState).not.toHaveBeenCalled();
    expect(submitButton().getAttribute('aria-busy')).toBe('true');
    expect(submitButton().disabled).toBe(true);
    // A second click while pending does not submit again.
    await act(async () => submitButton().click());
    expect(handleSubmit).toHaveBeenCalledTimes(1);
    await act(async () => request.resolve());
    expect(setModalState).toHaveBeenCalledWith('INACTIVE');
  });

  it('keeps a failure in the dialog as a destructive alert', async () => {
    const request = deferred();
    const setModalState = await renderModal(() => request.promise, vi.fn(), {
      error: 'Could not delete the agent.',
    });
    expect(document.querySelector('[data-slot="alert"]')).toBeNull();
    await act(async () => submitButton().click());
    await act(async () => request.reject(new Error('boom')));
    expect(setModalState).not.toHaveBeenCalled();
    const alert = document.querySelector('[data-slot="alert"]')!;
    expect(alert.getAttribute('data-variant')).toBe('destructive');
    expect(alert.textContent).toContain('Could not delete the agent.');
    expect(submitButton().disabled).toBe(false);
  });

  it('falls back to a generic failure message', async () => {
    await renderModal(() => Promise.reject(new Error('boom')));
    await act(async () => submitButton().click());
    expect(
      document.querySelector('[data-slot="alert"]')?.textContent,
    ).toContain('common.actionFailed');
  });

  it('renders children as the body', async () => {
    await renderModal(vi.fn(), vi.fn(), {
      children: <p data-testid="body">Extra</p>,
    });
    expect(document.querySelector('[data-testid="body"]')).not.toBeNull();
  });
});
