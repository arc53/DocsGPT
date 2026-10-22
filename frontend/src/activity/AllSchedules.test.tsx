import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

const service = vi.hoisted(() => ({ listAll: vi.fn() }));
vi.mock('../api/services/schedulesService', () => ({ default: service }));
vi.mock('../agents/schedules/RunLog', () => ({ default: () => null }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { TooltipProvider } from '@/components/ui/tooltip';

import schedulesReducer from '../agents/schedules/schedulesSlice';
import type { UserSchedule } from '../agents/types/schedule';
import AllSchedules from './AllSchedules';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const schedule = (overrides: Partial<UserSchedule>): UserSchedule => ({
  id: 's1',
  user_id: 'u1',
  agent_id: 'a1',
  trigger_type: 'recurring',
  name: 'Daily digest',
  instruction: 'Summarise tickets.',
  status: 'active',
  cron: '0 15 * * 1-5',
  timezone: 'UTC',
  tool_allowlist: [],
  created_via: 'ui',
  consecutive_failure_count: 0,
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-01T00:00:00Z',
  ...overrides,
});

const makeStore = () =>
  configureStore({
    reducer: {
      schedules: schedulesReducer,
      preference: () => ({ token: 'tok', agents: [] }),
    },
  });

describe('AllSchedules', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    service.listAll.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = async () => {
    await act(async () => {
      root.render(
        <Provider store={makeStore()}>
          <TooltipProvider>
            <MemoryRouter>
              <AllSchedules />
            </MemoryRouter>
          </TooltipProvider>
        </Provider>,
      );
    });
    await act(async () => {
      await Promise.resolve();
    });
  };

  const headings = () =>
    Array.from(container.querySelectorAll('h2')).map((h) => h.textContent);

  it('groups by agent and puts the chat-made schedules last', async () => {
    service.listAll.mockResolvedValue({
      schedules: [
        schedule({
          id: 's3',
          agent_id: null,
          name: 'Monday RFQ review',
          origin_conversation_id: 'c1',
          origin_conversation_name: 'Rotterdam market check',
        }),
        schedule({
          id: 's2',
          agent_id: 'a2',
          agent_name: 'Support',
          team: true,
        }),
        schedule({ id: 's1', agent_id: 'a1', agent_name: 'Deal Desk' }),
      ],
    });
    await render();
    const titles = headings();
    expect(titles[0]).toContain('Deal Desk');
    expect(titles[1]).toContain('Support');
    expect(titles[2]).toContain('activity.schedules.createdInChat');
    const chatLink =
      container.querySelector<HTMLAnchorElement>('a[href="/c/c1"]');
    expect(chatLink?.textContent).toContain('Rotterdam market check');
    // A text link in the meta line: the link colour and the shared focus ring.
    expect(chatLink?.dataset.variant).toBe('link');
    expect(chatLink?.dataset.size).toBe('text');
    expect(chatLink?.className).toContain('text-link');
    expect(chatLink?.className).not.toContain('text-primary');
    expect(
      container.querySelector('a[href="/agents/manage/schedules/a1"]'),
    ).not.toBeNull();
    // A teammate's agent is marked as managed through a team.
    const sections = Array.from(container.querySelectorAll('section'));
    expect(sections[1].textContent).toContain('teamAccess.editor');
    expect(sections[0].textContent).not.toContain('teamAccess.editor');
  });

  it('shows the empty state when there are no schedules', async () => {
    service.listAll.mockResolvedValue({ schedules: [] });
    await render();
    expect(container.textContent).toContain('activity.schedules.empty');
  });

  it('offers a retry when the list fails to load', async () => {
    service.listAll.mockRejectedValue(new Error('boom'));
    await render();
    expect(container.textContent).toContain('activity.schedules.loadError');
  });
});
