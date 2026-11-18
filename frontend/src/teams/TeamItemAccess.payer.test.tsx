import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) => {
      if (!options) return key;
      const params = Object.entries(options)
        .filter(([name]) => name !== 'interpolation')
        .map(([name, value]) => `${name}=${value}`)
        .join(',');
      return `${key}(${params})`;
    },
    i18n: { language: 'en' },
  }),
}));

const mocks = vi.hoisted(() => ({
  takeOver: vi.fn(),
  dispatch: vi.fn(),
}));

vi.mock('react-redux', () => ({
  useDispatch: () => mocks.dispatch,
  useSelector: (selector: (s: unknown) => unknown) =>
    selector({ preference: { token: 'tok' } }),
}));

vi.mock('../api/services/payerService', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  default: { takeOverOutsideAccess: mocks.takeOver },
}));

// The confirm is tested on its own: here it only has to call `onConfirm`,
// close on success and stay open on a refusal.
vi.mock('../payer/TakeOverModal', async () => {
  const { useState } = await import('react');
  return {
    default: function MockTakeOver({
      kind,
      name,
      modalState,
      setModalState,
      onConfirm,
    }: {
      kind: string;
      name: string;
      modalState: string;
      setModalState: (s: string) => void;
      onConfirm: () => Promise<unknown>;
    }) {
      const [failed, setFailed] = useState(false);
      if (modalState !== 'ACTIVE') return null;
      return (
        <div data-testid="take-over" data-kind={kind} data-name={name}>
          {failed ? <p data-testid="take-over-failed" /> : null}
          <button
            type="button"
            data-testid="take-over-confirm"
            onClick={() =>
              onConfirm().then(
                () => setModalState('INACTIVE'),
                () => setFailed(true),
              )
            }
          />
        </div>
      );
    },
  };
});

import { PayerApiError } from '../api/services/payerService';
import type { OutsideAccess } from '../payer/types';
import TeamItemAccess, { type TeamItemShares } from './TeamItemAccess';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const DANA = { user_id: 'u2', label: 'dana@meridian.example' };

const info = (outside: Partial<OutsideAccess> = {}): TeamItemShares => ({
  shares: [],
  workspace: { kind: 'team', team_id: 't1', name: 'Operations' },
  members_count: 12,
  access: 'admin',
  team_role: 'admin',
  origin: 'team',
  outside_access: {
    api_key: true,
    public_link: false,
    webhook: true,
    paid_by: DANA,
    paused_for: null,
    can_take_over: true,
    ...outside,
  },
});

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
  document.body.innerHTML = '';
  mocks.takeOver.mockReset();
  mocks.dispatch.mockReset();
});

const render = (shares: TeamItemShares) => {
  act(() => {
    root.render(
      <MemoryRouter>
        <TeamItemAccess
          resourceType="agent"
          resourceId="a1"
          resourceName="Carrier desk"
          info={shares}
          currentUserId="u1"
        />
      </MemoryRouter>,
    );
  });
};

const rowOf = (key: string) =>
  [...container.querySelectorAll('[data-slot="list-row"]')].find((row) =>
    row.textContent?.includes(`workspace.share.${key}`),
  ) as HTMLElement | undefined;
const takeOverButtons = () =>
  [...container.querySelectorAll('button')].filter(
    (b) => b.textContent === 'payer.common.takeOver.submit',
  );

describe('TeamItemAccess: who pays for outside access', () => {
  it('reads "On · paid by" on each row that is on, and Off on the rest', () => {
    render(info());
    expect(rowOf('apiKey')?.textContent).toContain(
      'workspace.share.onPaidBy(name=dana@meridian.example)',
    );
    expect(rowOf('webhook')?.textContent).toContain(
      'workspace.share.onPaidBy(name=dana@meridian.example)',
    );
    expect(rowOf('publicLink')?.textContent).toContain('workspace.share.off');
  });

  it('offers Take over on the rows that are on, only with can_take_over', () => {
    render(info());
    expect(takeOverButtons()).toHaveLength(2);
    expect(rowOf('publicLink')?.querySelector('button')).toBeNull();
    render(info({ can_take_over: false }));
    expect(takeOverButtons()).toHaveLength(0);
  });

  it('says why a paused row is paused, in the warning tone', () => {
    render(
      info({
        paused_for: {
          reason: 'payer_out_of_allowance',
          until: `${new Date().getFullYear()}-12-01T00:00:00Z`,
        },
      }),
    );
    const row = rowOf('apiKey')!;
    expect(row.textContent).toContain('payer.access.pausedBecause(reason=');
    expect(row.textContent).toContain(
      'payer.common.pause.outOfAllowance(name=dana@meridian.example,date=',
    );
    expect(row.querySelector('.text-warning')).not.toBeNull();
    // An Off row has nothing to pause.
    expect(rowOf('publicLink')?.textContent).not.toContain(
      'payer.access.pausedBecause',
    );
  });

  it('names the team the payer left', () => {
    render(info({ paused_for: { reason: 'payer_left', until: null } }));
    expect(rowOf('webhook')?.textContent).toContain(
      'payer.common.pause.payerLeft(name=dana@meridian.example,team=Operations)',
    );
  });

  it('words a pause it does not know as plain Paused', () => {
    render(
      info({
        paused_for: { reason: 'something_new' as never, until: null },
      }),
    );
    expect(rowOf('apiKey')?.textContent).toContain('payer.access.paused');
    expect(rowOf('apiKey')?.textContent).not.toContain(
      'payer.access.pausedBecause',
    );
  });

  it('takes over and shows the outside access the server answered with', async () => {
    mocks.takeOver.mockResolvedValue({
      changed: true,
      outside_access: {
        api_key: true,
        public_link: false,
        webhook: true,
        paid_by: { user_id: 'u1', label: 'lena@meridian.example' },
        paused_for: null,
        can_take_over: false,
      },
    });
    render(info({ paused_for: { reason: 'payer_left', until: null } }));
    await act(async () => takeOverButtons()[0].click());
    const dialog = container.querySelector('[data-testid="take-over"]');
    expect(dialog?.getAttribute('data-kind')).toBe('outside_access');
    expect(dialog?.getAttribute('data-name')).toBe('Carrier desk');
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('[data-testid="take-over-confirm"]')!
        .click(),
    );
    expect(mocks.takeOver).toHaveBeenCalledWith('a1', 'tok');
    expect(rowOf('apiKey')?.textContent).toContain(
      'workspace.share.onPaidBy(name=workspace.share.payerYou)',
    );
    expect(rowOf('apiKey')?.textContent).not.toContain('payer.access.paused');
    expect(takeOverButtons()).toHaveLength(0);
    expect(container.querySelector('[data-testid="take-over"]')).toBeNull();
    expect(mocks.dispatch).toHaveBeenCalledWith(
      expect.objectContaining({
        payload: expect.objectContaining({
          variant: 'success',
          message: 'payer.access.takenOver',
        }),
      }),
    );
  });

  it('keeps the dialog open and the rows as they were on a refusal', async () => {
    mocks.takeOver.mockRejectedValue(
      new PayerApiError(403, 'no', 'workspace_role_required'),
    );
    render(info());
    await act(async () => takeOverButtons()[0].click());
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('[data-testid="take-over-confirm"]')!
        .click(),
    );
    expect(
      container.querySelector('[data-testid="take-over-failed"]'),
    ).not.toBeNull();
    expect(rowOf('apiKey')?.textContent).toContain(
      'workspace.share.onPaidBy(name=dana@meridian.example)',
    );
    expect(mocks.dispatch).not.toHaveBeenCalled();
  });
});
