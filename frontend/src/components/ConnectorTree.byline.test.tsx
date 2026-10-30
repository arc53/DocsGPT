import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// The byline as TreeBrowser gets it: the tree itself is mocked out, so the
// test reads the prop directly.
const { captured, t } = vi.hoisted(() => ({
  captured: [] as ((counts: { files: number; tokens: number }) => string)[],
  // One function, as react-i18next's own `t` is between renders.
  t: (key: string, opts?: Record<string, unknown>) =>
    opts && 'when' in opts ? `${key}(${String(opts.when)})` : key,
}));

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t }) }));

vi.mock('react-redux', () => ({
  useSelector: () => null,
  useDispatch: () => vi.fn(),
}));

vi.mock('../api/services/userService', () => ({ default: {} }));

vi.mock('./tree/useReingestWait', () => ({
  useReingestSseWaiter: () => ({
    waitForChange: async () => ({ terminal: 'completed', reason: null }),
    mountedRef: { current: true },
  }),
}));

vi.mock('./tree/TreeBrowser', () => ({
  default: ({
    renderByline,
  }: {
    renderByline: (counts: { files: number; tokens: number }) => string;
  }) => {
    captured.push(renderByline);
    return null;
  },
}));

import ConnectorTree from './ConnectorTree';
import { EMPTY_VALUE } from '../utils/dateTimeUtils';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('ConnectorTree byline', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    captured.length = 0;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (syncedAt?: string) => {
    await act(async () => {
      root.render(
        <ConnectorTree
          docId="doc"
          sourceName="Handbook"
          onBackToDocuments={vi.fn()}
          syncFrequency="weekly"
          syncedAt={syncedAt}
        />,
      );
    });
  };

  const byline = () => captured[captured.length - 1]({ files: 2, tokens: 9 });

  it.each([
    ['missing', undefined],
    ['unparseable', 'not a date'],
  ])('says the sync time is unknown when it is %s', async (_label, at) => {
    await render(at);
    // As the source's card does: never a bare "synced ".
    expect(byline()).toBe(
      `settings.sources.filesByline · settings.sources.website.synced(${EMPTY_VALUE})`,
    );
  });

  it('keeps one byline function across renders', async () => {
    await render('2026-10-21T10:00:00Z');
    await render('2026-10-21T10:00:00Z');
    expect(captured.length).toBeGreaterThan(1);
    expect(new Set(captured).size).toBe(1);
  });
});
