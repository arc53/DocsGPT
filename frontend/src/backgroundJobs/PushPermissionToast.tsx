import { BellRing } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import { Button } from '../components/ui/button';
import {
  Toast,
  ToastContent,
  ToastFooter,
  ToastHeader,
  ToastMessage,
  ToastTitle,
} from '../components/ui/toast';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';

import {
  closePushPrompt,
  selectPushConfig,
  selectPushPromptOpen,
} from './backgroundSlice';
import { enablePush, savePushChoice } from './webPush';

/**
 * "Get notified when it's done?": the in-context Web Push prompt. It opens
 * the first time a job goes to the background or a monitor is set up (see
 * `backgroundListener`), never on page load; the browser's permission dialog
 * comes only from Enable. Either answer is remembered in this browser.
 */
export default function PushPermissionToast() {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const open = useSelector(selectPushPromptOpen);
  const config = useSelector(selectPushConfig);
  const token = useSelector(selectToken);
  const [busy, setBusy] = useState(false);

  if (!open || !config?.enabled || !config.public_key) return null;
  const publicKey = config.public_key;

  const notNow = () => {
    savePushChoice('dismissed');
    dispatch(closePushPrompt());
  };

  const enable = async () => {
    setBusy(true);
    try {
      const permission = await enablePush(publicKey, token);
      if (permission === 'granted') {
        savePushChoice('enabled');
      } else {
        savePushChoice('dismissed');
        if (permission === 'denied') {
          dispatch(
            showActionToast({
              variant: 'destructive',
              message: t('backgroundJobs.push.blocked'),
            }),
          );
        }
      }
    } catch {
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: t('backgroundJobs.push.failed'),
        }),
      );
    } finally {
      setBusy(false);
      dispatch(closePushPrompt());
    }
  };

  return (
    <Toast data-testid="push-permission-prompt">
      <ToastHeader variant="info">
        <ToastTitle wrap>{t('backgroundJobs.push.promptTitle')}</ToastTitle>
        <BellRing aria-hidden className="text-info size-4 shrink-0" />
      </ToastHeader>
      <ToastContent>
        <ToastMessage size="sm">
          {t('backgroundJobs.push.promptBody')}
        </ToastMessage>
      </ToastContent>
      <ToastFooter>
        <Button
          type="button"
          variant="ghost"
          size="xs"
          shape="pill"
          onClick={notNow}
          disabled={busy}
        >
          {t('backgroundJobs.push.notNow')}
        </Button>
        <Button
          type="button"
          size="xs"
          shape="pill"
          onClick={() => void enable()}
          disabled={busy}
        >
          {t('backgroundJobs.push.enable')}
        </Button>
      </ToastFooter>
    </Toast>
  );
}
