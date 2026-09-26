import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const testSourceRetrieval = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    testSourceRetrieval: (...args: unknown[]) => testSourceRetrieval(...args),
  },
}));

import type { Doc } from '../models/misc';
import TestRetrievalModal from './TestRetrievalModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const doc = (config: Doc['config']): Doc =>
  ({ id: 'src-1', name: 'Handbook', config }) as Doc;

const alerts = () =>
  Array.from(document.body.querySelectorAll<HTMLElement>('[role="alert"]'));

describe('TestRetrievalModal notices', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    testSourceRetrieval.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = (document: Doc) =>
    act(() => {
      root.render(
        <TestRetrievalModal
          modalState="ACTIVE"
          setModalState={() => undefined}
          document={document}
        />,
      );
    });

  it('sizes the Run button to the query field row', () => {
    render(doc(undefined));
    const run = Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('[data-slot="button"]'),
    ).find((b) => b.textContent === 'settings.sources.testRetrieval.run');
    expect(run?.getAttribute('data-size')).toBe('field');
    expect(run?.getAttribute('data-shape')).toBe('pill');
    // 38px, the height of the Input beside it.
    expect(run?.className).toContain('h-9.5');
  });

  it('shows an invalid prescreen config as a warning Alert with an icon', () => {
    render(
      doc({
        retrieval: { chunks: 10, prescreen: { candidate_k: 5, max_keep: 3 } },
      } as Doc['config']),
    );

    const warning = alerts().find((el) =>
      el.textContent?.includes(
        'settings.sources.configModal.prescreenInvalidHint',
      ),
    );
    expect(warning).toBeDefined();
    expect(warning?.className).toContain('text-warning');
    expect(warning?.querySelector('svg')).not.toBeNull();
  });

  it('shows a failed run as a destructive Alert with an icon', async () => {
    testSourceRetrieval.mockRejectedValue(new Error('network'));
    render(doc(undefined));

    const input =
      document.body.querySelector<HTMLInputElement>('input[type="text"]');
    expect(input).not.toBeNull();
    const setValue = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )?.set;
    act(() => {
      setValue?.call(input, 'fuel surcharge');
      input?.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      input?.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });

    const error = alerts().find((el) =>
      el.textContent?.includes('settings.sources.testRetrieval.errors.failed'),
    );
    expect(error).toBeDefined();
    expect(error?.className).toContain('text-destructive');
    expect(error?.querySelector('svg')).not.toBeNull();
  });
});
