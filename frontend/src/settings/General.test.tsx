import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const dispatch = vi.fn();
vi.mock('react-redux', () => ({
  useSelector: () => [],
  useDispatch: () => dispatch,
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: () => undefined, language: 'en' },
  }),
}));
vi.mock('../hooks', () => ({
  useDarkTheme: () => [false, () => undefined],
}));
vi.mock('../components/PageToolbar', () => ({ default: () => null }));
vi.mock('./Prompts', () => ({ default: () => null }));

import General from './General';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  dispatch.mockClear();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe('General danger zone', () => {
  it('is the tinted card with the header inside and one field pill', async () => {
    await act(async () => root.render(<General />));
    const button = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'settings.general.deleteAllLabel',
    )!;
    expect(button.dataset.variant).toBe('destructive-outline');
    expect(button.dataset.size).toBe('field');
    expect(button.dataset.shape).toBe('pill');
    const card = button.closest<HTMLElement>('[data-slot="card"]')!;
    expect(card.dataset.tone).toBe('destructive');
    expect(card.dataset.padding).toBe('lg');
    const header = card.querySelector('[data-slot="section-header"]')!;
    expect(header.querySelector('h2')?.textContent).toBe(
      'settings.general.sections.dangerZone',
    );
    expect(header.textContent).toContain(
      'settings.general.deleteAllDescription',
    );
    // No SettingRow left inside the zone.
    expect(card.querySelector('[data-slot="setting-row"]')).toBeNull();
    await act(async () => button.click());
    expect(dispatch).toHaveBeenCalled();
  });
});
