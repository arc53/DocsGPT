import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-redux', () => ({ useSelector: () => 'token' }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

// A stand-in for the drop target: one click drops a valid spec.
vi.mock('../components/ui/dropzone', () => ({
  Dropzone: ({
    onDrop,
  }: {
    onDrop: (files: File[], rejections: unknown[]) => void;
  }) => (
    <button
      type="button"
      data-testid="drop"
      onClick={() => onDrop([new File(['{}'], 'spec.json')], [])}
    />
  ),
}));

const parseSpec = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: { parseSpec: (...a: unknown[]) => parseSpec(...a) },
}));

import ImportSpecModal from './ImportSpecModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  parseSpec.mockResolvedValue({
    ok: true,
    json: async () => ({
      success: true,
      metadata: {
        title: 'Meridian',
        description: '',
        version: '2',
        base_url: 'https://api.example.com',
      },
      actions: [
        { name: 'get_status', method: 'get', url: 'https://api.example.com/s' },
        { name: 'book', method: 'post', url: 'https://api.example.com/b' },
      ],
    }),
  });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe('ImportSpecModal action rows', () => {
  it('hover on accent and mark checked rows as chosen tiles', async () => {
    await act(async () =>
      root.render(
        <ImportSpecModal
          modalState="ACTIVE"
          setModalState={() => undefined}
          onImport={() => undefined}
        />,
      ),
    );
    await act(async () =>
      document
        .querySelector<HTMLButtonElement>('[data-testid="drop"]')!
        .click(),
    );
    const parse = Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent === 'modals.importSpec.parse',
    )!;
    await act(async () => parse.click());
    const rows = Array.from(
      document.querySelectorAll<HTMLLabelElement>(
        'label[for^="import-spec-action-"]',
      ),
    );
    expect(rows).toHaveLength(2);
    for (const row of rows) {
      expect(row.className).toContain('hover:bg-accent');
      expect(row.className).not.toContain('hover:bg-muted');
      expect(row.className).toContain(
        'has-[[data-state=checked]]:border-primary',
      );
      expect(row.className).toContain(
        'has-[[data-state=checked]]:bg-primary/5',
      );
    }
  });
});

describe('ImportSpecModal metadata', () => {
  // O5: the summary is a place on the modal's surface (outline Card), the
  // version a DescriptionList, and the Base URL field sits on bg-card.
  it('groups the parsed summary in an outline Card', async () => {
    await act(async () =>
      root.render(
        <ImportSpecModal
          modalState="ACTIVE"
          setModalState={() => undefined}
          onImport={() => undefined}
        />,
      ),
    );
    await act(async () =>
      document
        .querySelector<HTMLButtonElement>('[data-testid="drop"]')!
        .click(),
    );
    const parse = Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent === 'modals.importSpec.parse',
    )!;
    await act(async () => parse.click());
    const title = Array.from(document.querySelectorAll('h3')).find(
      (h) => h.textContent === 'Meridian',
    )!;
    const card = title.closest<HTMLElement>('[data-slot="card"]')!;
    expect(card).not.toBeNull();
    expect(card.dataset.variant).toBe('outline');
    expect(card.className).not.toContain('bg-muted');
    const list = card.querySelector<HTMLElement>(
      '[data-slot="description-list"]',
    )!;
    expect(list).not.toBeNull();
    expect(list.querySelector('dt')?.textContent).toBe(
      'modals.importSpec.version',
    );
    const value = list.querySelector('dd')!;
    expect(value.textContent).toBe('2');
    expect(value.className).toContain('font-mono');
    const input = card.querySelector<HTMLInputElement>('input[type="text"]')!;
    expect(input.dataset.variant).toBe('default');
    const label = card.querySelector('[data-slot="form-field-label"]')!;
    expect(label.className).toContain('bg-card');
    expect(label.className).not.toContain('bg-muted');
  });
});
