import { X } from 'lucide-react';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import { Button } from '../components/ui/button';
import {
  Toast,
  ToastActions,
  ToastHeader,
  ToastTitle,
} from '../components/ui/toast';

import { dismissActionToast, selectActionToast } from './actionToastSlice';

export const ACTION_TOAST_DISMISS_MS = 4500;

/**
 * The result of an action a page just ran (dispatch `showActionToast`),
 * shown as a card in the shared `ToastViewport` mounted in App.tsx. Returns
 * only the card; the viewport is the live region. Auto-dismisses after
 * 4.5s, restarting whenever a new result replaces the card.
 */
export default function ActionToast() {
  const dispatch = useDispatch();
  const { t } = useTranslation();
  const toast = useSelector(selectActionToast);
  const id = toast?.id;

  useEffect(() => {
    if (id === undefined) return;
    const timer = window.setTimeout(
      () => dispatch(dismissActionToast(id)),
      ACTION_TOAST_DISMISS_MS,
    );
    return () => window.clearTimeout(timer);
  }, [id, dispatch]);

  if (!toast) return null;

  return (
    <Toast>
      <ToastHeader variant={toast.variant}>
        <ToastTitle wrap>{toast.message}</ToastTitle>
        <ToastActions>
          <Button
            type="button"
            variant="ghost-muted"
            size="icon-sm"
            onClick={() => dispatch(dismissActionToast(toast.id))}
            aria-label={t('notifications.dismiss')}
          >
            <X className="size-4" />
          </Button>
        </ToastActions>
      </ToastHeader>
    </Toast>
  );
}
