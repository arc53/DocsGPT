import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && 'count' in opts ? `${key}:${opts.count}` : key,
  }),
}));

const service = vi.hoisted(() => ({ linearWorkspace: vi.fn() }));
vi.mock('../api/services/connectorsService', () => ({ default: service }));

import LinearPicker, {
  EMPTY_LINEAR_SELECTION,
  linearSourceName,
  type LinearSelection,
} from './LinearPicker';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const WORKSPACE = {
  success: true,
  teams: [
    { id: 't1', key: 'ENG', name: 'Engineering' },
    { id: 't2', key: 'DES', name: 'Design' },
  ],
  projects: [
    { id: 'p1', name: 'Launch', state: 'Started', teams: ['Engineering'] },
  ],
};

describe('LinearPicker', () => {
  let root: Root;
  let container: HTMLDivElement;

  beforeEach(() => {
    service.linearWorkspace.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (
    value: LinearSelection = EMPTY_LINEAR_SELECTION,
    onChange = vi.fn(),
    onReconnect?: () => void,
  ) => {
    await act(async () => {
      root.render(
        <LinearPicker
          connectionId="conn-1"
          token={null}
          value={value}
          onChange={onChange}
          onReconnect={onReconnect}
        />,
      );
    });
    return onChange;
  };

  const checkboxes = () =>
    Array.from(
      container.querySelectorAll<HTMLButtonElement>('[role="checkbox"]'),
    );
  const switches = () =>
    Array.from(
      container.querySelectorAll<HTMLButtonElement>('[role="switch"]'),
    );

  it('lists the teams and projects to pick', async () => {
    service.linearWorkspace.mockResolvedValue(WORKSPACE);
    await render();
    expect(service.linearWorkspace).toHaveBeenCalledWith('conn-1', null);
    expect(container.textContent).toContain('Engineering');
    expect(container.textContent).toContain('ENG');
    expect(container.textContent).toContain('Launch');
    expect(checkboxes()).toHaveLength(3);
  });

  it('lists on the modal surface and counts what is picked', async () => {
    service.linearWorkspace.mockResolvedValue({
      ...WORKSPACE,
      projects: [
        {
          id: 'p1',
          name: 'Launch',
          state: 'Started',
          teams: ['Engineering', 'Design'],
        },
      ],
    });
    await render({
      ...EMPTY_LINEAR_SELECTION,
      teams: [{ id: 't1', key: 'ENG', name: 'Engineering' }],
      projects: [{ id: 'p1', name: 'Launch' }],
    });
    const cards = Array.from(container.querySelectorAll('[data-slot="card"]'));
    expect(cards).toHaveLength(2);
    for (const card of cards) {
      expect(card.getAttribute('data-variant')).toBe('outline');
      expect(card.className).not.toMatch(/max-h-|overflow-y-auto/);
    }
    expect(container.textContent).toContain('filePicker.itemsSelected:2');
    // The project's teams as a list in the UI language.
    expect(container.textContent).toContain('Started · Engineering, Design');
  });

  it('puts the search label on the modal surface', async () => {
    service.linearWorkspace.mockResolvedValue({
      ...WORKSPACE,
      teams: Array.from({ length: 9 }, (_, n) => ({
        id: `t${n}`,
        key: `T${n}`,
        name: `Team ${n}`,
      })),
    });
    await render();
    const label = container.querySelector('label')!;
    expect(label.className).toContain('bg-card');
  });

  it('picks a team with what the source needs to name it', async () => {
    service.linearWorkspace.mockResolvedValue(WORKSPACE);
    const onChange = await render();
    await act(async () => checkboxes()[0].click());
    expect(onChange).toHaveBeenCalledWith({
      ...EMPTY_LINEAR_SELECTION,
      teams: [{ id: 't1', key: 'ENG', name: 'Engineering' }],
    });
  });

  it('unpicks a picked project', async () => {
    service.linearWorkspace.mockResolvedValue(WORKSPACE);
    const picked = {
      ...EMPTY_LINEAR_SELECTION,
      projects: [{ id: 'p1', name: 'Launch' }],
    };
    const onChange = await render(picked);
    const project = checkboxes()[2];
    expect(project.getAttribute('aria-checked')).toBe('true');
    await act(async () => project.click());
    expect(onChange).toHaveBeenCalledWith({
      ...picked,
      projects: [],
    });
  });

  it('keeps comments on by default and offers documents once a project is picked', async () => {
    service.linearWorkspace.mockResolvedValue(WORKSPACE);
    const onChange = await render();
    const [comments, documents] = switches();
    expect(comments.getAttribute('aria-checked')).toBe('true');
    expect(documents.disabled).toBe(true);
    await act(async () => comments.click());
    expect(onChange).toHaveBeenCalledWith({
      ...EMPTY_LINEAR_SELECTION,
      includeComments: false,
    });
    await render({
      ...EMPTY_LINEAR_SELECTION,
      projects: [{ id: 'p1', name: 'Launch' }],
    });
    expect(switches()[1].disabled).toBe(false);
  });

  it('filters by the search text', async () => {
    service.linearWorkspace.mockResolvedValue({
      ...WORKSPACE,
      teams: Array.from({ length: 9 }, (_, n) => ({
        id: `t${n}`,
        key: `T${n}`,
        name: n === 4 ? 'Platform' : `Team ${n}`,
      })),
    });
    await render();
    const input = container.querySelector<HTMLInputElement>('input')!;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!;
    await act(async () => {
      setter.call(input, 'platf');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(checkboxes()).toHaveLength(1);
    expect(container.textContent).toContain('Platform');
  });

  it('asks to reconnect when the sign-in stopped working', async () => {
    service.linearWorkspace.mockResolvedValue({
      success: false,
      code: 'reconnect',
    });
    const onReconnect = vi.fn();
    await render(EMPTY_LINEAR_SELECTION, vi.fn(), onReconnect);
    expect(container.textContent).toContain(
      'settings.connectors.detail.expired',
    );
    const reconnect = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'settings.connectors.status.reconnect',
    )!;
    await act(async () => reconnect.click());
    expect(onReconnect).toHaveBeenCalled();
  });

  it('offers a retry when Linear did not answer', async () => {
    service.linearWorkspace.mockResolvedValueOnce({ success: false });
    await render();
    expect(container.textContent).toContain(
      'settings.connectors.linear.loadFailed',
    );
    service.linearWorkspace.mockResolvedValueOnce(WORKSPACE);
    const retry = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    )!;
    await act(async () => retry.click());
    expect(checkboxes()).toHaveLength(3);
  });

  it('names a source after what it syncs', () => {
    expect(linearSourceName(EMPTY_LINEAR_SELECTION)).toBe('');
    expect(
      linearSourceName({
        ...EMPTY_LINEAR_SELECTION,
        teams: [{ id: 't1', key: 'ENG', name: 'Engineering' }],
        projects: [{ id: 'p1', name: 'Launch' }],
      }),
    ).toBe('Linear · Engineering, Launch');
  });
});
