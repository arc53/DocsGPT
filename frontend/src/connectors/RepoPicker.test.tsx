import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && 'count' in opts ? `${key}:${opts.count}` : key,
  }),
}));

const service = vi.hoisted(() => ({ repositories: vi.fn() }));
vi.mock('../api/services/connectorsService', () => ({ default: service }));

const install = vi.hoisted(() => ({
  options: null as null | { install?: boolean; onSuccess: () => void },
  start: vi.fn(),
}));
vi.mock('../components/ConnectorAuth', () => ({
  useConnectorAuth: (options: { install?: boolean; onSuccess: () => void }) => {
    install.options = options;
    return install.start;
  },
}));

import RepoPicker from './RepoPicker';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const REPOS = [
  {
    full_name: 'octocat/private',
    private: true,
    description: 'Secret stuff',
    default_branch: 'main',
    updated_at: '2026-09-01T00:00:00Z',
    html_url: 'https://github.com/octocat/private',
  },
  {
    full_name: 'octocat/hello-world',
    private: false,
    description: '',
    default_branch: 'main',
    updated_at: '2026-08-01T00:00:00Z',
    html_url: 'https://github.com/octocat/hello-world',
  },
];

describe('RepoPicker', () => {
  let root: Root;
  let container: HTMLDivElement;

  beforeEach(() => {
    service.repositories.mockReset();
    install.start.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (
    value: string | null,
    onChange = vi.fn(),
    onReconnect?: () => void,
  ) => {
    await act(async () => {
      root.render(
        <RepoPicker
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

  const radios = () =>
    Array.from(container.querySelectorAll<HTMLButtonElement>('[role="radio"]'));

  it('lists the repositories and picks one', async () => {
    service.repositories.mockResolvedValue({
      success: true,
      repositories: REPOS,
      install_url: null,
    });
    const onChange = await render(null);
    expect(service.repositories).toHaveBeenCalledWith('conn-1', null);
    expect(radios().map((r) => r.textContent)).toEqual([
      expect.stringContaining('octocat/private'),
      expect.stringContaining('octocat/hello-world'),
    ]);
    await act(async () => radios()[1].click());
    expect(onChange).toHaveBeenCalledWith('octocat/hello-world');
  });

  it('marks the picked repository', async () => {
    service.repositories.mockResolvedValue({
      success: true,
      repositories: REPOS,
      install_url: null,
    });
    await render('octocat/private');
    expect(radios()[0].getAttribute('aria-checked')).toBe('true');
    expect(radios()[1].getAttribute('aria-checked')).toBe('false');
    // The chosen row carries the selected tint as well as the check.
    expect(radios()[0].getAttribute('aria-current')).toBe('true');
    expect(radios()[1].getAttribute('aria-current')).toBeNull();
  });

  it('lists on the modal surface: an outline card with no scroll cap', async () => {
    service.repositories.mockResolvedValue({
      success: true,
      repositories: REPOS,
      install_url: 'https://github.com/apps/docsgpt/installations/new',
    });
    await render(null);
    const card = container.querySelector('[data-slot="card"]')!;
    expect(card.getAttribute('data-variant')).toBe('outline');
    expect(card.className).not.toMatch(/max-h-|overflow-y-auto/);
    // The search label rests on the modal's card surface.
    const label = container.querySelector('label')!;
    expect(label.className).toContain('bg-card');
    expect(label.className).not.toContain('bg-background');
    // The link icon trails its label.
    const choose = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('settings.connectors.github.chooseRepositories'),
    )!;
    expect(choose.lastElementChild?.tagName.toLowerCase()).toBe('svg');
  });

  it('filters by the search text', async () => {
    service.repositories.mockResolvedValue({
      success: true,
      repositories: REPOS,
      install_url: null,
    });
    await render(null);
    const input = container.querySelector<HTMLInputElement>('input')!;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!;
    await act(async () => {
      setter.call(input, 'hello');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(radios()).toHaveLength(1);
    expect(radios()[0].textContent).toContain('octocat/hello-world');
  });

  it('sends a GitHub App sign-in to choose repositories, then reloads', async () => {
    service.repositories.mockResolvedValueOnce({
      success: true,
      repositories: [],
      install_url: 'https://github.com/apps/docsgpt/installations/new',
    });
    await render(null);
    expect(container.textContent).toContain(
      'settings.connectors.github.noAppRepositories',
    );
    const choose = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('settings.connectors.github.chooseRepositories'),
    )!;
    await act(async () => choose.click());
    expect(install.start).toHaveBeenCalled();
    expect(install.options?.install).toBe(true);
    service.repositories.mockResolvedValueOnce({
      success: true,
      repositories: REPOS,
      install_url: 'https://github.com/apps/docsgpt/installations/new',
    });
    await act(async () => install.options!.onSuccess());
    expect(radios()).toHaveLength(2);
  });

  it('asks to reconnect when the token stopped working', async () => {
    service.repositories.mockResolvedValue({
      success: false,
      code: 'reconnect',
    });
    const onReconnect = vi.fn();
    await render(null, vi.fn(), onReconnect);
    expect(container.textContent).toContain(
      'settings.connectors.detail.expired',
    );
    const reconnect = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'settings.connectors.status.reconnect',
    )!;
    await act(async () => reconnect.click());
    expect(onReconnect).toHaveBeenCalled();
  });
});
