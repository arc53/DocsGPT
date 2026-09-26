import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useDarkTheme } from './index';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('useDarkTheme', () => {
  let container: HTMLDivElement;

  beforeEach(() => {
    localStorage.setItem('selectedTheme', 'Light');
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: false,
      media: query,
      addListener: () => {},
      removeListener: () => {},
    }));
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    container.remove();
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it('updates every consumer when one of them toggles the theme', async () => {
    let toggle: (() => void) | undefined;
    let logoIsDark: boolean | undefined;

    function Settings() {
      const [, toggleTheme] = useDarkTheme();
      toggle = toggleTheme;
      return null;
    }
    function Logo() {
      [logoIsDark] = useDarkTheme();
      return null;
    }

    const root = createRoot(container);
    await act(async () => {
      root.render(
        <>
          <Settings />
          <Logo />
        </>,
      );
    });
    expect(logoIsDark).toBe(false);

    await act(async () => toggle?.());
    expect(logoIsDark).toBe(true);

    await act(async () => toggle?.());
    expect(logoIsDark).toBe(false);

    await act(async () => root.unmount());
  });
});
