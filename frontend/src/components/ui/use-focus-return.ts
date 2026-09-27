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
 * to where the user was instead of dropping it on <body>.
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
          ? active
          : null;
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
      if (target?.isConnected) target.focus();
    },
    [onCloseAutoFocus],
  );

  return {
    onOpenAutoFocus: handleOpenAutoFocus,
    onCloseAutoFocus: handleCloseAutoFocus,
  };
}

export { useFocusReturn };
