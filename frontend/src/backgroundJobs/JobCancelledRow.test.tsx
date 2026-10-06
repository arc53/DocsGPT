import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import type { ToolCallsType } from '../conversation/types';
import { sseEventReceived } from '../notifications/notificationsSlice';
import backgroundReducer from './backgroundSlice';
import JobCancelledRows from './JobCancelledRow';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const CALL: ToolCallsType = {
  tool_name: 'code_executor',
  action_name: 'run_code',
  call_id: 'call-1',
  arguments: {},
  status: 'pending',
  job_id: 'j1',
};

describe('JobCancelledRows', () => {
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

  const makeStore = () =>
    configureStore({ reducer: { background: backgroundReducer } });

  const render = async (
    calls: ToolCallsType[],
    store = makeStore(),
  ): Promise<ReturnType<typeof makeStore>> => {
    await act(async () =>
      root.render(
        <Provider store={store}>
          <JobCancelledRows toolCalls={calls} />
        </Provider>,
      ),
    );
    return store;
  };

  const rows = () =>
    container.querySelectorAll('[data-testid="job-cancelled-row"]');

  it('says a job ended when the user cancels it, live', async () => {
    const store = await render([CALL]);
    expect(rows()).toHaveLength(0);
    await act(async () => {
      store.dispatch(
        sseEventReceived({
          id: 'e1',
          type: 'job.updated',
          payload: { job_id: 'j1', status: 'cancelled' },
        }),
      );
    });
    expect(rows()).toHaveLength(1);
    expect(rows()[0].textContent).toContain('backgroundJobs.wake.cancelled');
    expect(rows()[0].textContent).toContain('Run code');
  });

  it('keeps saying so after a reload, from the saved call', async () => {
    await render([
      { ...CALL, status: 'error', job_status: 'cancelled' },
      { ...CALL, call_id: 'call-2', job_id: 'j2', job_status: 'completed' },
      { ...CALL, call_id: 'call-3', job_id: undefined },
    ]);
    expect(rows()).toHaveLength(1);
  });
});
