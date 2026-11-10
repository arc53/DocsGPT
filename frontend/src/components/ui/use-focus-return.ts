import * as React from 'react';

type AutoFocusHandler = (event: Event) => void;

/**
 * Focus return for Radix dialogs (Sheet, Modal, DialogContent): on close,
 * focus goes back to whatever had it when the dialog opened, and nowhere if
 * nothing did.
 *
 * Radix focuses the trigger on close even when it never had focus. A tap on
 * iOS (and a click in Safari) doesn't focus a button, so after a phone sheet
 * the trigger would light up with a focus-visible ring out of nowhere. After a
 * keyboard open the trigger did have focus and gets it back as before, and a
 * dialog opened without a trigger (a Modal from a menu row) now returns focus
 * to where the user was instead of dropping it on <body>: for a menu row, the
 * button that opened the menu.
 *
 * Focus the page moved on its own as the dialog closed (outside it) stays.
 *
 * Returns the two handlers to pass to the Radix Content. The caller's own
 * handlers run first; a caller that calls `preventDefault()` on close keeps
 * control of focus.
 */
function useFocusReturn(
  onOpenAutoFocus?: AutoFocusHandler,
  onCloseAutoFocus?: AutoFocusHandler,
) {
  const returnTo = React.useRef<HTMLElement | null>(null);

  const handleOpenAutoFocus = React.useCallback(
    (event: Event) => {
      // Still the element that had focus before the dialog opened.
      const active = document.activeElement;
      returnTo.current =
        active instanceof HTMLElement && active !== document.body
          ? menuOpener(active)
          : // A menu that closed without an exit animation already took
            // its focused row away.
            lastMenuOpener?.isConnected
            ? lastMenuOpener
            : null;
      lastMenuOpener = null;
      onOpenAutoFocus?.(event);
    },
    [onOpenAutoFocus],
  );

  const handleCloseAutoFocus = React.useCallback(
    (event: Event) => {
      onCloseAutoFocus?.(event);
      const target = returnTo.current;
      returnTo.current = null;
      if (event.defaultPrevented) return;
      event.preventDefault();
      // The page already moved focus on as the dialog closed (a phone sheet
      // stepping aside for a control in the page): leave it there.
      const active = document.activeElement;
      if (active && active !== document.body && active.isConnected) return;
      if (target?.isConnected) target.focus();
    },
    [onCloseAutoFocus],
  );

  return {
    onOpenAutoFocus: handleOpenAutoFocus,
    onCloseAutoFocus: handleCloseAutoFocus,
  };
}

/**
 * A dialog opened from a menu item (Preview in a ⋯) returns focus to the
 * button that opened the menu: the item is gone once the menu closes. Radix
 * labels a menu by its trigger, a submenu by the item that opened it.
 */
function menuOpener(element: HTMLElement): HTMLElement {
  let current = element;
  for (;;) {
    const menu = current.closest('[role="menu"]');
    const id = menu?.getAttribute('aria-labelledby');
    const trigger = id ? document.getElementById(id) : null;
    if (!trigger || trigger === current) return current;
    current = trigger;
  }
}

// The button that opened the menu whose row had focus last, while focus is
// still in that menu (null once it moved elsewhere).
let lastMenuOpener: HTMLElement | null = null;

if (typeof document !== 'undefined') {
  document.addEventListener(
    'focusin',
    (event) => {
      const target = event.target;
      lastMenuOpener =
        target instanceof HTMLElement && target.closest('[role="menu"]')
          ? menuOpener(target)
          : null;
    },
    true,
  );
}

export { useFocusReturn };
