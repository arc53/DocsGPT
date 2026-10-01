import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-redux', () => ({
  useSelector: () => null,
  useDispatch: () => () => undefined,
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const search = vi.hoisted(() => ({ query: '', total: 0 }));
const sections = { template: [], user: [], team: [], shared: [] };
vi.mock('./hooks/useAgentSearch', () => ({
  useAgentSearch: () => ({
    searchQuery: search.query,
    setSearchQuery: () => undefined,
    filteredAgentsBySection: sections,
    totalAgentsBySection: {
      template: 0,
      user: search.total,
      team: 0,
      shared: 0,
    },
    hasAnyAgents: search.total > 0,
    hasFilteredResults: false,
    isDataLoaded: { template: true, user: true, team: true, shared: true },
  }),
}));
vi.mock('./hooks/useAgentsFetch', () => ({
  useAgentsFetch: () => ({
    isLoading: { template: false, user: false, team: false, shared: false },
    refetchFolders: async () => undefined,
    refetchUserAgents: async () => undefined,
  }),
}));
vi.mock('../navigation/SectionShell', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('../navigation/SectionPills', () => ({ default: () => null }));
vi.mock('../components/PageToolbar', () => ({ default: () => null }));
vi.mock('../modals/ImportAgentModal', () => ({ default: () => null }));
vi.mock('./components/AgentTypeModal', () => ({ default: () => null }));

import AgentsList from './AgentsList';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

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
  window.history.replaceState(null, '', '/');
});

const render = async (path: string) => {
  window.history.replaceState(null, '', path);
  await act(async () =>
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <AgentsList />
      </MemoryRouter>,
    ),
  );
};

const empties = () =>
  Array.from(
    container.querySelectorAll<HTMLElement>('[data-slot="empty-state"]'),
  );

const expectTextOnlySm = (el: HTMLElement | undefined) => {
  expect(el?.dataset.size).toBe('sm');
  expect(el?.querySelector('svg')).toBeNull();
};

describe('AgentsList empties', () => {
  it('says no search results once, as a small text-only EmptyState', async () => {
    search.query = 'zzz';
    search.total = 3;
    await render('/agents/manage');
    const found = empties().filter((el) =>
      el.textContent?.includes('agents.noSearchResults'),
    );
    expect(found).toHaveLength(1);
    expectTextOnlySm(found[0]);
    expect(found[0].textContent).toContain('agents.tryDifferentSearch');
  });

  it('says no search results in a filtered view the same way', async () => {
    search.query = 'zzz';
    search.total = 3;
    await render('/agents/manage/mine');
    const found = empties().filter((el) =>
      el.textContent?.includes('agents.noSearchResults'),
    );
    expect(found).toHaveLength(1);
    expectTextOnlySm(found[0]);
  });

  it('offers New Agent in an empty section, with no stray margin', async () => {
    search.query = '';
    search.total = 0;
    await render('/agents/manage');
    const empty = empties().find((el) =>
      el.textContent?.includes('agents.sections.user.emptyState'),
    );
    expectTextOnlySm(empty);
    const button = empty?.querySelector('button');
    expect(button?.textContent).toBe('agents.newAgent');
    expect(button?.className).not.toContain('ml-2');
  });

  it('offers New Agent in an empty filtered view', async () => {
    search.query = '';
    search.total = 0;
    await render('/agents/manage/mine');
    const empty = empties().find((el) =>
      el.textContent?.includes('agents.sections.user.emptyState'),
    );
    expectTextOnlySm(empty);
    expect(empty?.querySelector('button')?.textContent).toBe('agents.newAgent');
  });
});
