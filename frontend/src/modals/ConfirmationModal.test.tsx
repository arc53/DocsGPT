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
