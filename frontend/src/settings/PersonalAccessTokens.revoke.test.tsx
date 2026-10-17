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

// The revoke confirm's props; the test calls its handleSubmit directly.
const confirmProps: { current: Record<string, unknown> | null } = {
  current: null,
};
vi.mock('../modals/ConfirmationModal', () => ({
  default: (props: Record<string, unknown>) => {
    confirmProps.current = props;
    return null;
  },
}));
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

import { AccessTokenApiError } from '../api/services/patService';
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

describe('PersonalAccessTokens revoke', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    list.mockReset().mockResolvedValue({
      tokens: [TOKEN_ROW],
      scopes: [],
      policy: null,
    });
    revoke.mockReset();
    confirmProps.current = null;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const openRevoke = async () => {
    await act(async () => {
      root.render(<PersonalAccessTokens />);
    });
    const button = container.querySelector<HTMLButtonElement>(
      'button[aria-label="settings.accessTokens.revokeAria"]',
    )!;
    await act(async () => button.click());
    expect(confirmProps.current?.modalState).toBe('ACTIVE');
  };

  const submit = async () => {
    const handleSubmit = confirmProps.current!.handleSubmit as () => unknown;
    let result: unknown;
    await act(async () => {
      result = handleSubmit();
      await (result as Promise<unknown>).catch(() => undefined);
    });
    return result as Promise<unknown>;
  };

  const pageAlert = () =>
    container.querySelector('[data-slot="alert"]')?.textContent ?? null;

  it('a failed revoke rejects so the confirm shows the server message, not the page', async () => {
    revoke.mockRejectedValue(new AccessTokenApiError('Token is locked.', 500));
    await openRevoke();
    await expect(submit()).rejects.toThrow();
    expect(confirmProps.current?.error).toBe('Token is locked.');
    // The dialog keeps its name and the page shows no Alert of its own.
    expect(confirmProps.current?.message).toBe(
      'settings.accessTokens.revokeWarning',
    );
    expect(pageAlert()).toBeNull();
    expect(container.textContent).toContain('CI deploy');
  });

  it('falls back to revokeError when the server sends no message', async () => {
    revoke.mockRejectedValue(new AccessTokenApiError('', 500));
    await openRevoke();
    await expect(submit()).rejects.toThrow();
    expect(confirmProps.current?.error).toBe(
      'settings.accessTokens.revokeError',
    );
  });

  it('a 404 (already revoked) resolves and drops the row', async () => {
    revoke.mockRejectedValue(new AccessTokenApiError('', 404));
    await openRevoke();
    await expect(submit()).resolves.toBeUndefined();
    expect(container.textContent).not.toContain('CI deploy');
  });

  it('a successful revoke resolves and drops the row', async () => {
    revoke.mockResolvedValue({ success: true });
    await openRevoke();
    await expect(submit()).resolves.toBeUndefined();
    expect(container.textContent).not.toContain('CI deploy');
  });
});
