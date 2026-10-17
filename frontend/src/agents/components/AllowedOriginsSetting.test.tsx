import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { AgentConfig } from '../types';

const t = (key: string, options?: Record<string, unknown>) =>
  options?.origin ? `${key}:${options.origin}` : key;
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t }),
}));

import AllowedOriginsSetting, {
  MAX_ALLOWED_ORIGINS,
  originsIncomplete,
  parseOrigin,
} from './AllowedOriginsSetting';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('parseOrigin', () => {
  it.each([
    ['https://Example.com/', 'https://example.com'],
    ['  http://localhost:3000  ', 'http://localhost:3000'],
    ['https://example.com:443', 'https://example.com'],
    ['https://bücher.de', 'https://xn--bcher-kva.de'],
    ['http://[::1]:8080', 'http://[::1]:8080'],
  ])('stores %s as %s', (value, origin) => {
    expect(parseOrigin(value)).toEqual({ origin });
  });

  it.each([
    'example.com',
    'ftp://example.com',
    'https://*.example.com',
    'https://user:pass@example.com',
    '',
  ])('refuses %s as not an origin', (value) => {
    expect(parseOrigin(value)).toEqual({ error: 'invalid' });
  });

  it.each([
    'https://example.com/docs',
    'https://example.com/?q=1',
    'https://example.com/#top',
  ])('refuses %s for its path', (value) => {
    expect(parseOrigin(value)).toEqual({ error: 'path' });
  });
});

describe('originsIncomplete', () => {
  it('is true only while restricting with nothing listed', () => {
    expect(originsIncomplete(undefined)).toBe(false);
    expect(originsIncomplete({ restrict_origins: false })).toBe(false);
    expect(originsIncomplete({ restrict_origins: true })).toBe(true);
    expect(
      originsIncomplete({ restrict_origins: true, allowed_origins: [] }),
    ).toBe(true);
    expect(
      originsIncomplete({
        restrict_origins: true,
        allowed_origins: ['https://a.com'],
      }),
    ).toBe(false);
  });
});

describe('AllowedOriginsSetting', () => {
  let container: HTMLDivElement;
  let root: Root;
  let onChange: ReturnType<typeof vi.fn<(next: AgentConfig) => void>>;

  beforeEach(() => {
    onChange = vi.fn<(next: AgentConfig) => void>();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (config?: AgentConfig, disabled = false) => {
    await act(async () => {
      root.render(
        <AllowedOriginsSetting
          config={config}
          onChange={onChange}
          disabled={disabled}
        />,
      );
    });
  };

  const input = () => container.querySelector('input') as HTMLInputElement;
  const addButton = () =>
    [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'agents.form.advanced.origins.add',
    ) as HTMLButtonElement;
  const toggle = () =>
    container.querySelector('[role="switch"]') as HTMLButtonElement;
  const alertText = () =>
    container.querySelector('[role="alert"]')?.textContent;

  const type = async (value: string) => {
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!;
      setter.call(input(), value);
      input().dispatchEvent(new Event('input', { bubbles: true }));
    });
  };
  const pressEnter = async () => {
    await act(async () => {
      input().dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });
  };
  const click = async (el: HTMLElement) => {
    await act(async () => el.click());
  };

  const restricted: AgentConfig = {
    restrict_origins: true,
    allowed_origins: ['https://a.com'],
  };

  it('turning the switch on keeps the saved list', async () => {
    await render({
      restrict_origins: false,
      allowed_origins: ['https://a.com'],
    });
    expect(input().disabled).toBe(true);
    await click(toggle());
    expect(onChange).toHaveBeenCalledWith({
      restrict_origins: true,
      allowed_origins: ['https://a.com'],
    });
  });

  it('adds a typed origin in its canonical form', async () => {
    await render(restricted);
    await type('https://Docs.Example.com/');
    await click(addButton());
    expect(onChange).toHaveBeenCalledWith({
      restrict_origins: true,
      allowed_origins: ['https://a.com', 'https://docs.example.com'],
    });
    expect(input().value).toBe('');
  });

  it('adds on Enter', async () => {
    await render(restricted);
    await type('http://localhost:3000');
    await pressEnter();
    expect(onChange).toHaveBeenCalledWith({
      restrict_origins: true,
      allowed_origins: ['https://a.com', 'http://localhost:3000'],
    });
  });

  it('explains a path instead of adding it', async () => {
    await render(restricted);
    await type('https://b.com/page');
    await click(addButton());
    expect(onChange).not.toHaveBeenCalled();
    expect(alertText()).toBe('agents.form.advanced.origins.errors.path');
  });

  it('explains an address that is not an origin', async () => {
    await render(restricted);
    await type('b.com');
    await click(addButton());
    expect(onChange).not.toHaveBeenCalled();
    expect(alertText()).toBe('agents.form.advanced.origins.errors.invalid');
  });

  it('refuses a duplicate after normalizing it', async () => {
    await render(restricted);
    await type('HTTPS://A.com:443/');
    await click(addButton());
    expect(onChange).not.toHaveBeenCalled();
    expect(alertText()).toBe(
      'agents.form.advanced.origins.errors.duplicate:https://a.com',
    );
  });

  it('stops at the server limit', async () => {
    const full = Array.from(
      { length: MAX_ALLOWED_ORIGINS },
      (_, i) => `https://s${i}.example.com`,
    );
    await render({ restrict_origins: true, allowed_origins: full });
    await type('https://one-more.example.com');
    await click(addButton());
    expect(onChange).not.toHaveBeenCalled();
    expect(alertText()).toBe('agents.form.advanced.origins.errors.full');
  });

  it('removes an origin from its chip', async () => {
    await render({
      restrict_origins: true,
      allowed_origins: ['https://a.com', 'https://b.com'],
    });
    const remove = container.querySelector(
      '[aria-label="agents.form.advanced.origins.remove:https://a.com"]',
    ) as HTMLButtonElement;
    await click(remove);
    expect(onChange).toHaveBeenCalledWith({
      restrict_origins: true,
      allowed_origins: ['https://b.com'],
    });
  });

  it('asks for an origin while restricting with none', async () => {
    await render({ restrict_origins: true, allowed_origins: [] });
    expect(alertText()).toBe('agents.form.advanced.origins.errors.required');
  });

  it('shows the list read-only to a role that cannot edit policy', async () => {
    await render(restricted, true);
    expect(toggle().disabled).toBe(true);
    expect(input()).toBeNull();
    expect(addButton()).toBeUndefined();
    expect(container.textContent).toContain('https://a.com');
    expect(
      container.querySelector(
        '[aria-label="agents.form.advanced.origins.remove:https://a.com"]',
      ),
    ).toBeNull();
  });
});
