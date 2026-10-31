import { useEffect, useState, type MouseEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { type NavigateOptions, useNavigate } from 'react-router-dom';

import ConfirmationModal from '../modals/ConfirmationModal';

/**
 * How a programmatic exit leaves: the router's options, plus `beforeLeave`,
 * which runs only once leaving is allowed, right before the navigation (a
 * "Try in chat" that clears the chat's selection must not clear it when the
 * reader stays).
 */
export type LeaveOptions = NavigateOptions & { beforeLeave?: () => void };

/** A programmatic exit, a builder's guarded one or the router's. */
export type LeaveTo = (path: string, options?: LeaveOptions) => void;

/**
 * Leave now through the router, running `beforeLeave` first.
 *
 * Args:
 *   navigate: The router's navigate.
 *   path: Where to go.
 *   options: The router's options and `beforeLeave`.
 */
export function leaveNow(
  navigate: (path: string, options?: NavigateOptions) => void,
  path: string,
  options: LeaveOptions = {},
): void {
  const { beforeLeave, ...navigateOptions } = options;
  beforeLeave?.();
  navigate(path, navigateOptions);
}

/**
 * Asks before a builder's own exits leave unsaved work: a picker footer's
 * "Go to Tools / Knowledge / Prompts" link and Upload's Browse connectors.
 * With nothing unsaved they go at once; otherwise a confirm asks "Leave
 * without saving?" with Leave or Cancel. A link opened in a new tab (Cmd,
 * Ctrl, Shift or middle click) never asks. The app's router
 * can't block every navigation, so it covers the exits the builder draws;
 * a reload, a closed tab or a typed URL gets the browser's own prompt
 * (`beforeunload`) while something is unsaved, and none once it's saved.
 *
 * Args:
 *   dirty: Whether leaving now would lose changes.
 *
 * Returns:
 *   `onNavigate(close)`, a link's click handler that closes the picker
 *   first; `leaveTo(path, options)` for a programmatic exit (a dialog's
 *   button, Browse connectors); and `dialog` to render.
 */
export function useLeaveGuard(dirty: boolean): {
  onNavigate: (
    close?: () => void,
  ) => (event: MouseEvent<HTMLAnchorElement>) => void;
  leaveTo: LeaveTo;
  dialog: ReactNode;
} {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [pending, setPending] = useState<{
    path: string;
    options?: LeaveOptions;
  } | null>(null);

  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Older browsers show the prompt only when returnValue is set.
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [dirty]);

  const leaveTo: LeaveTo = (path, options) => {
    if (dirty) setPending({ path, options });
    else leaveNow(navigate, path, options);
  };
  const onNavigate =
    (close?: () => void) => (event: MouseEvent<HTMLAnchorElement>) => {
      close?.();
      // A Cmd, Ctrl, Shift or middle click opens a new tab or window and
      // leaves the builder where it is: nothing to lose, nothing to ask.
      const newTab =
        event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0;
      if (!dirty || newTab) return;
      event.preventDefault();
      const href = event.currentTarget.getAttribute('href');
      if (href) setPending({ path: href });
    };

  return {
    onNavigate,
    leaveTo,
    dialog: pending ? (
      <ConfirmationModal
        message={t('agents.form.leave.title')}
        description={t('agents.form.leave.description')}
        modalState="ACTIVE"
        setModalState={(state) => state !== 'ACTIVE' && setPending(null)}
        submitLabel={t('agents.form.leave.submit')}
        variant="destructive"
        handleSubmit={() => {
          setPending(null);
          leaveNow(navigate, pending.path, pending.options);
        }}
      />
    ) : null,
  };
}
