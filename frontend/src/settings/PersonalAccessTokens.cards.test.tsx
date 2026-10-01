import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));

// A stable t: the page reloads its tokens whenever t changes.
const mockT = (key: string) => key;
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT }),
}));

vi.mock('../modals/ConfirmationModal', () => ({ default: () => null }));
vi.mock('../modals/AccessTokenCreatedModal', () => ({ default: () => null }));
vi.mock('../modals/CreateAccessTokenModal', () => ({ default: () => null }));
vi.mock('../modals/RegenerateAccessTokenModal', () => ({
  default: () => null,
}));
vi.mock('../components/PageToolbar', () => ({
  default: ({ children }: { children?: React.ReactNode }) => (
    <div data-slot="page-toolbar">{children}</div>
  ),
}));

const list = vi.fn();
const revoke = vi.fn();
vi.mock('../api/services/patService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/services/patService')>()),
  default: {
    list: (...a: unknown[]) => list(...a),
    revoke: (...a: unknown[]) => revoke(...a),
  },
}));

import PersonalAccessTokens from './PersonalAccessTokens';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const TOKEN_ROW = {
  id: 'pat-1',
  name: 'CI deploy',
  token_prefix: 'dgpt_ab12',
  scopes: ['agents:read'],
  resource_filter: null,
  created_at: '2026-09-01T10:00:00Z',
  last_used_at: null,
  expires_at: null,
  revoked_at: null,
};

describe('PersonalAccessTokens phone cards', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    list.mockReset().mockResolvedValue({
      tokens: [TOKEN_ROW],
      scopes: [],
      policy: null,
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  // O5: a token is a thing you regenerate or revoke as a whole, so its phone
  // card is a filled Card (same pixels as the old hand-built bg-muted li).
  it('renders each token as a filled Card list item', async () => {
    await act(async () => {
      root.render(<PersonalAccessTokens />);
    });
    const item = container.querySelector<HTMLElement>('ul.lg\\:hidden > li')!;
    expect(item).not.toBeNull();
    expect(item.tagName).toBe('LI');
    expect(item.dataset.slot).toBe('card');
    expect(item.dataset.variant).toBe('filled');
    expect(item.dataset.padding).toBe('default');
    expect(item.className.split(' ')).toEqual(
      expect.arrayContaining(['bg-muted', 'rounded-2xl', 'gap-3', 'p-4']),
    );
    expect(item.textContent).toContain('CI deploy');
  });
});
