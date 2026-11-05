import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const language = vi.hoisted(() => ({ current: 'de' }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: language.current },
  }),
}));

import AgendaList from './AgendaList';
import type { ScheduleEvent } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

// Mon 12 Oct 2026, local time.
const DAY = new Date(2026, 9, 12);
const slot: ScheduleEvent = {
  kind: 'schedule',
  schedule_id: 's1',
  name: 'Digest',
  agent_id: null,
  agent_name: null,
  trigger_type: 'recurring',
  cron: '0 9 * * *',
  timezone: 'UTC',
  origin_conversation_id: null,
  origin_conversation_name: null,
  frequent: false,
  at: new Date(2026, 9, 12, 9).toISOString(),
  state: 'planned',
};

describe('AgendaList day headings', () => {
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
  });

  const render = (lang: string) => {
    language.current = lang;
    act(() =>
      root.render(
        <AgendaList
          days={[DAY]}
          events={[slot]}
          monitors={[]}
          now={new Date(2026, 9, 1).getTime()}
          onSelectEvent={vi.fn()}
          onSelectBlock={vi.fn()}
          onSelectMonitor={vi.fn()}
        />,
      ),
    );
    return container.textContent ?? '';
  };

  it("names the month in the reader's language", () => {
    // The weekday was localized and the month always English ("Mo. 12 Oct").
    expect(render('de')).toContain('12. Okt.');
  });

  it('keeps day-month order in English', () => {
    expect(render('en')).toContain('Mon 12 Oct');
  });
});
