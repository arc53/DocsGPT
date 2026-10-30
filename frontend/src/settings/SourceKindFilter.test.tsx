import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import type { Doc } from '../models/misc';
import { useSourceKindFilter } from './SourceKindFilter';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const doc = (id: string, fields: Partial<Doc> = {}): Doc => ({
  id,
  name: id,
  date: '',
  model: '',
  ...fields,
});

const website = { hosts: ['a.io'], pages: 1 };
const library = [
  doc('upload'),
  doc('site', { website }),
  doc('team-site', { website, ownership: 'team' }),
  doc('wiki', { type: 'wiki' }),
];

describe('useSourceKindFilter', () => {
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

  function Picker({ docs, open }: { docs: Doc[]; open: boolean }) {
    const { docs: shown, filters } = useSourceKindFilter(docs, open);
    return (
      <>
        <div data-testid="filters">{filters}</div>
        <ul>
          {shown.map((d) => (
            <li key={d.id}>{d.name}</li>
          ))}
        </ul>
      </>
    );
  }

  const render = (docs: Doc[], open = true) =>
    act(() => root.render(<Picker docs={docs} open={open} />));
  const rows = () =>
    Array.from(container.querySelectorAll('li')).map((li) => li.textContent);
  const items = () =>
    Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[data-slot="toggle-group-item"]',
      ),
    );
  const pick = (kind: string) =>
    act(() =>
      items()
        .find((b) =>
          b.textContent?.startsWith(`settings.sources.kinds.${kind}`),
        )!
        .click(),
    );

  it('counts the kinds, leaves out empty ones, and is xs', () => {
    render(library);
    expect(
      items().map((b) => [
        b.firstChild?.textContent,
        b.querySelector('[data-slot="count"]')?.textContent,
      ]),
    ).toEqual([
      ['settings.sources.kinds.all', '4'],
      ['settings.sources.kinds.files', '1'],
      ['settings.sources.kinds.websites', '2'],
      ['settings.sources.kinds.wikis', '1'],
      ['settings.sources.kinds.shared', '1'],
    ]);
    expect(
      container.querySelector('[data-slot="toggle-group"]')?.className,
    ).toContain('overflow-x-auto');
  });

  it('narrows the list to the picked kind', () => {
    render(library);
    pick('websites');
    expect(rows()).toEqual(['site', 'team-site']);
    pick('shared');
    expect(rows()).toEqual(['team-site']);
  });

  it('opens on All again', () => {
    render(library);
    pick('wikis');
    expect(rows()).toEqual(['wiki']);
    render(library, false);
    render(library, true);
    expect(rows()).toEqual(['upload', 'site', 'team-site', 'wiki']);
  });

  it('draws nothing when the list has one kind', () => {
    render([doc('a'), doc('b')]);
    expect(container.querySelector('[data-testid="filters"]')!.innerHTML).toBe(
      '',
    );
  });
});
