import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) => {
      if (!options) return key;
      const values = Object.entries(options)
        .filter(([name]) => name !== 'interpolation')
        .map(([name, value]) => `${name}=${value}`)
        .join(',');
      return `${key}(${values})`;
    },
    i18n: { language: 'en' },
  }),
}));

const service = vi.hoisted(() => ({ takeOverSchedule: vi.fn() }));
vi.mock('../../api/services/payerService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/services/payerService')>()),
  default: { takeOverSchedule: service.takeOverSchedule },
}));

import { PayerApiError } from '../../api/services/payerService';
import actionToastReducer from '../../notifications/actionToastSlice';
import type { UserSchedule } from '../types/schedule';
import schedulesReducer, {
  loadAllSchedules,
  loadSchedulesForAgent,
  takeOverSchedule,
} from './schedulesSlice';
import useScheduleTakeOver from './useScheduleTakeOver';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const schedule: UserSchedule = {
  id: 's1',
  user_id: 'u-dana',
  agent_id: 'a1',
  trigger_type: 'recurring',
  name: 'Weekly lane report',
  instruction: 'Summarise lane volumes.',
  status: 'active',
  cron: '0 7 * * 1',
  timezone: 'Europe/Berlin',
  tool_allowlist: [],
  created_via: 'ui',
  consecutive_failure_count: 3,
  created_at: '2026-09-01T00:00:00Z',
  updated_at: '2026-09-01T00:00:00Z',
  paid_by: { user_id: 'u-dana', label: 'Dana' },
  paused_for: { reason: 'payer_left' },
  can_take_over: true,
  agent_name: 'Carrier desk',
};

// The answer of a per-agent read has no group names.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
const { agent_name: _name, ...bare } = schedule;
const taken = {
  ...bare,
  user_id: 'u-me',
  consecutive_failure_count: 0,
  paid_by: { user_id: 'u-me', label: 'me@meridian.test' },
  paused_for: null,
  can_take_over: false,
  updated_at: '2026-11-16T10:00:00Z',
};

const makeStore = () => {
  const store = configureStore({
    reducer: {
      schedules: schedulesReducer,
      actionToast: actionToastReducer,
      preference: () => ({ token: 'tok' }),
    },
  });
  const arg = { agentId: 'a1', token: 'tok' };
  store.dispatch(loadSchedulesForAgent.pending('load', arg));
  store.dispatch(
    loadSchedulesForAgent.fulfilled(
      { agentId: 'a1', schedules: [schedule] },
      'load',
      arg,
    ),
  );
  store.dispatch(loadAllSchedules.pending('all', { token: 'tok' }));
  store.dispatch(
    loadAllSchedules.fulfilled([schedule], 'all', { token: 'tok' }),
  );
  return store;
};

function Harness() {
  const { requestTakeOver, takeOverModal } = useScheduleTakeOver();
  return (
    <>
      <button type="button" onClick={() => requestTakeOver(schedule)}>
        open
      </button>
      {takeOverModal}
    </>
  );
}

let container: HTMLDivElement;
let root: Root;
let store: ReturnType<typeof makeStore>;

beforeEach(() => {
  service.takeOverSchedule.mockReset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  store = makeStore();
  act(() => {
    root.render(
      <Provider store={store}>
        <Harness />
      </Provider>,
    );
  });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  document.body.innerHTML = '';
});

const text = () => document.body.textContent ?? '';
const button = (label: string) =>
  [...document.body.querySelectorAll('button')].find(
    (b) => b.textContent === label,
  );
const open = () => act(() => button('open')!.click());
const confirm = () =>
  act(async () => button('payer.common.takeOver.submit')!.click());

describe('Take over a schedule', () => {
  it('asks first, naming the schedule and who pays now', () => {
    open();
    expect(text()).toContain(
      'payer.common.takeOver.title(name=Weekly lane report)',
    );
    expect(text()).toContain(
      'payer.common.takeOver.schedule.youPayDetail(name=Dana)',
    );
    expect(service.takeOverSchedule).not.toHaveBeenCalled();
  });

  it('calls the service, replaces the row in both lists and says so', async () => {
    service.takeOverSchedule.mockResolvedValue({
      schedule: taken,
      changed: true,
    });
    open();
    await confirm();
    expect(service.takeOverSchedule).toHaveBeenCalledWith('s1', 'tok');
    const state = store.getState();
    expect(state.schedules.byAgent.a1[0]).toMatchObject({
      user_id: 'u-me',
      paused_for: null,
      can_take_over: false,
      consecutive_failure_count: 0,
    });
    // The cross-agent row keeps the names the response doesn't carry.
    expect(state.schedules.all?.[0]).toMatchObject({
      user_id: 'u-me',
      paid_by: { user_id: 'u-me' },
      agent_name: 'Carrier desk',
    });
    expect(state.actionToast.current).toMatchObject({
      variant: 'success',
      message: 'payer.schedules.takenOver',
    });
    // The dialog closed.
    expect(button('payer.common.takeOver.submit')).toBeUndefined();
  });

  it.each([
    [403, 'workspace_role_required', 'payer.common.errors.roleRequired'],
    [409, 'take_over_team_only', 'payer.common.errors.teamOnly'],
    [429, 'max_schedules', 'payer.common.errors.maxSchedules'],
    [404, 'schedule_not_found', 'payer.common.errors.notFound'],
    [
      403,
      'not_available_to_tokens',
      'payer.common.errors.notAvailableToTokens',
    ],
  ])(
    'keeps the dialog open on a %s %s, worded',
    async (status, code, message) => {
      service.takeOverSchedule.mockRejectedValue(
        new PayerApiError(status, 'refused', code),
      );
      open();
      await confirm();
      expect(text()).toContain(message);
      expect(button('payer.common.takeOver.submit')).toBeDefined();
      // Nothing changed.
      expect(store.getState().schedules.byAgent.a1[0].user_id).toBe('u-dana');
      expect(store.getState().actionToast.current).toBeNull();
    },
  );

  it('words a network failure generically', async () => {
    service.takeOverSchedule.mockRejectedValue(new TypeError('offline'));
    open();
    await confirm();
    expect(text()).toContain('payer.common.takeOver.failed');
  });
});

describe('takeOverSchedule in the slice', () => {
  it('rejects with the refusal code, so the dialog can word it', async () => {
    service.takeOverSchedule.mockRejectedValue(
      new PayerApiError(429, 'too many', 'max_schedules'),
    );
    const result = await store.dispatch(
      takeOverSchedule({ id: 's1', token: 'tok' }),
    );
    expect(result.type).toBe(takeOverSchedule.rejected.type);
    expect(
      (result as { error: { name?: string; code?: string } }).error,
    ).toMatchObject({ name: 'PayerApiError', code: 'max_schedules' });
  });
});
