import { useState, type MouseEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import ConfirmationModal from '../modals/ConfirmationModal';

/**
 * Asks before a builder's own exits leave unsaved work: a picker footer's
 * "Go to Tools / Knowledge / Prompts" link and Upload's Browse connectors.
 * With nothing unsaved they go at once; otherwise a confirm asks "Leave
 * without saving?" with Leave or Cancel. The app's router
 * can't block every navigation, so it covers the exits the builder draws.
 *
 * Args:
 *   dirty: Whether leaving now would lose changes.
 *
 * Returns:
 *   `onNavigate(close)`, a link's click handler that closes the picker
 *   first; `leaveTo(path)` for a programmatic exit; and `dialog` to render.
 */
export function useLeaveGuard(dirty: boolean): {
  onNavigate: (
    close?: () => void,
  ) => (event: MouseEvent<HTMLAnchorElement>) => void;
  leaveTo: (path: string) => void;
  dialog: ReactNode;
} {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [pending, setPending] = useState<string | null>(null);

  const leaveTo = (path: string) => {
    if (dirty) setPending(path);
    else navigate(path);
  };
  const onNavigate =
    (close?: () => void) => (event: MouseEvent<HTMLAnchorElement>) => {
      close?.();
      if (!dirty) return;
      event.preventDefault();
      setPending(event.currentTarget.getAttribute('href'));
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
          navigate(pending);
        }}
      />
    ) : null,
  };
}
