import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const logout = vi.fn();
vi.mock('../hooks/useTokenAuth', () => ({
  default: () => ({
    authType: 'oidc',
    userName: 'Lena Fischer',
    userEmail: 'lena.fischer@meridianfreight.com',
    userPicture: null,
    logout,
  }),
}));

import ProfileButton from './ProfileButton';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('ProfileButton', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    logout.mockReset();
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const open = () => {
    act(() => root.render(<ProfileButton />));
    const trigger = container.querySelector<HTMLButtonElement>(
      'button[aria-label="auth.account"]',
    )!;
    expect(trigger.getAttribute('aria-haspopup')).toBe('menu');
    act(() => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
    });
    return trigger;
  };

  it('is a DropdownMenu: an identity label and a Sign out menu item', () => {
    open();
    const menu = document.body.querySelector('[role="menu"]')!;
    expect(menu).not.toBeNull();
    const label = menu.querySelector('[data-slot="dropdown-menu-label"]')!;
    expect(label.textContent).toContain('Lena Fischer');
    expect(label.textContent).toContain('lena.fischer@meridianfreight.com');
    const items = Array.from(menu.querySelectorAll('[role="menuitem"]'));
    expect(items).toHaveLength(1);
    expect(items[0].textContent).toBe('auth.signOut');
    expect(items[0].getAttribute('data-testid')).toBe('oidc-signout');
    expect(menu.querySelector('button')).toBeNull();
  });

  it('signs out from the menu item', () => {
    open();
    const item = document.body.querySelector<HTMLElement>(
      '[data-testid="oidc-signout"]',
    )!;
    act(() => item.click());
    expect(logout).toHaveBeenCalledTimes(1);
  });
});
