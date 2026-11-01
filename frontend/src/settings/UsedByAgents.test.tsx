import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: unknown) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
  }),
}));

import UsedByAgents from './UsedByAgents';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('UsedByAgents', () => {
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

  // A draft's card doesn't open for anyone, and its chat refuses an
  // unfinished workflow: a reader who can't edit it gets its name, no link.
  it("names a draft the reader can't edit without linking it", async () => {
    await act(async () =>
      root.render(
        <MemoryRouter>
          <UsedByAgents
            usage={{
              agents: [
                {
                  id: 'a1',
                  name: 'Live',
                  can_edit: false,
                  status: 'published',
                },
                {
                  id: 'a2',
                  name: 'Their draft',
                  agent_type: 'workflow',
                  can_edit: false,
                  status: 'draft',
                },
                {
                  id: 'a3',
                  name: 'My draft',
                  agent_type: 'workflow',
                  can_edit: true,
                  status: 'draft',
                },
              ],
              others: 0,
            }}
          />
        </MemoryRouter>,
      ),
    );
    const trigger = container.querySelector('button')!;
    await act(async () => trigger.click());
    const content = document.querySelector('[data-slot="popover-content"]')!;
    const links = Array.from(content.querySelectorAll('a')).map((a) => [
      a.textContent,
      a.getAttribute('href'),
    ]);
    expect(links).toEqual([
      ['Live', '/agents/a1/c/new'],
      ['My draft', '/agents/manage/workflow/edit/a3'],
    ]);
    const items = Array.from(content.querySelectorAll('li')).map(
      (li) => li.textContent,
    );
    expect(items).toEqual(['Live', 'Their draft', 'My draft']);
    const plain = Array.from(content.querySelectorAll('li'))[1];
    expect(plain.querySelector('.truncate')?.getAttribute('title')).toBe(
      'Their draft',
    );
  });
});
