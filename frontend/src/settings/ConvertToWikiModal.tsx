import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import Spinner from '../components/Spinner';
import { Button } from '../components/ui/button';
import { Modal } from '../components/ui/modal';
import { ActiveState, Doc } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';

import {
  ConvertSummary,
  pollTaskOnce,
  startWikiConversion,
} from './wikiConvertUtils';

const POLL_INTERVAL_MS = 2000;

type Phase = 'confirm' | 'converting' | 'summary' | 'error';

interface ConvertToWikiModalProps {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  document: Doc | null;
  onConverted: () => void;
}

export default function ConvertToWikiModal({
  modalState,
  setModalState,
  document,
  onConverted,
}: ConvertToWikiModalProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);

  const [phase, setPhase] = useState<Phase>('confirm');
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<ConvertSummary | null>(null);
  const pollTimer = useRef<number | null>(null);
  const isActiveRef = useRef(true);

  const clearPoll = () => {
    if (pollTimer.current !== null) {
      window.clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  };

  const stopPolling = () => {
    isActiveRef.current = false;
    clearPoll();
  };

  useEffect(() => {
    if (modalState === 'ACTIVE') {
      isActiveRef.current = true;
      setPhase('confirm');
      setError(null);
      setSummary(null);
    }
    return stopPolling;
  }, [modalState, document]);

  const closeModal = () => {
    stopPolling();
    setModalState('INACTIVE');
  };

  const fail = (message?: string) => {
    setError(message ?? t('settings.sources.wiki.convert.errors.generic'));
    setPhase('error');
  };

  const poll = (taskId: string) => {
    pollTaskOnce(userService, taskId, token)
      .then((result) => {
        if (!isActiveRef.current) return;
        if (result.status === 'pending') {
          pollTimer.current = window.setTimeout(
            () => poll(taskId),
            POLL_INTERVAL_MS,
          );
          return;
        }
        if (result.status === 'done') {
          setSummary(result.summary);
          setPhase('summary');
          onConverted();
          return;
        }
        fail(result.message);
      })
      .catch(() => {
        if (!isActiveRef.current) return;
        fail();
      });
  };

  const handleConvert = async () => {
    if (!document?.id) return;
    setPhase('converting');
    setError(null);
    const start = await startWikiConversion(userService, document.id, token);
    if (start.status === 'enabled') {
      setSummary({ pagesCreated: 0, skipped: [] });
      setPhase('summary');
      onConverted();
      return;
    }
    if (start.status === 'task') {
      poll(start.taskId);
      return;
    }
    if (start.status === 'forbidden') {
      fail(t('settings.sources.wiki.convert.errors.forbidden'));
      return;
    }
    if (start.status === 'conflict') {
      fail(start.message ?? t('settings.sources.wiki.convert.errors.conflict'));
      return;
    }
    fail(start.message);
  };

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={(o) => !o && closeModal()}
      hideTitle
      title={t('settings.sources.wiki.convert.title')}
      size="md"
      mobileVariant="sheet"
      className="max-w-[480px]"
      isPerformingTask={phase === 'converting'}
    >
      <div className="flex flex-col gap-5 px-1 py-1">
        <h2 className="text-foreground text-xl font-semibold">
          {t('settings.sources.wiki.convert.title')}
        </h2>

        {phase === 'confirm' && (
          <>
            <p className="text-muted-foreground text-sm">
              {document?.name
                ? t('settings.sources.wiki.convert.intro', {
                    name: document.name,
                  })
                : t('settings.sources.wiki.convert.introGeneric')}
            </p>
            <ul className="text-muted-foreground list-disc space-y-1.5 pl-5 text-sm">
              <li>{t('settings.sources.wiki.convert.costReparse')}</li>
              <li>{t('settings.sources.wiki.convert.costSkipped')}</li>
              <li>{t('settings.sources.wiki.convert.costIrreversible')}</li>
            </ul>
            <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
              <Button
                type="button"
                variant="ghost"
                onClick={closeModal}
                className="w-full rounded-3xl px-6 sm:w-auto"
              >
                {t('cancel')}
              </Button>
              <Button
                type="button"
                onClick={handleConvert}
                className="w-full rounded-3xl px-6 sm:w-auto"
              >
                {t('settings.sources.wiki.convert.confirm')}
              </Button>
            </div>
          </>
        )}

        {phase === 'converting' && (
          <div className="flex flex-col items-center gap-3 py-6">
            <Spinner size="medium" />
            <p className="text-muted-foreground text-sm">
              {t('settings.sources.wiki.convert.inProgress')}
            </p>
          </div>
        )}

        {phase === 'summary' && summary && (
          <>
            <div className="rounded-xl bg-green-50 p-4 text-sm text-green-800 dark:bg-green-900/30 dark:text-green-200">
              {[
                t('settings.sources.wiki.convert.summaryPages', {
                  count: summary.pagesCreated,
                }),
                t('settings.sources.wiki.convert.summarySkipped', {
                  count: summary.skipped.length,
                }),
              ].join(' · ')}
            </div>
            {summary.skipped.length > 0 && (
              <div className="flex flex-col gap-1.5">
                <p className="text-foreground text-sm font-medium">
                  {t('settings.sources.wiki.convert.skippedHeading')}
                </p>
                <ul className="text-muted-foreground max-h-40 list-disc space-y-1 overflow-auto pl-5 text-xs">
                  {summary.skipped.map((s) => (
                    <li key={s.file} title={s.reason}>
                      {s.file}
                      {s.reason ? ` — ${s.reason}` : ''}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="flex justify-end">
              <Button
                type="button"
                onClick={closeModal}
                className="w-full rounded-3xl px-6 sm:w-auto"
              >
                {t('settings.sources.wiki.convert.done')}
              </Button>
            </div>
          </>
        )}

        {phase === 'error' && (
          <>
            <div className="rounded-xl bg-red-50 p-4 text-sm text-red-700 dark:bg-red-900/40 dark:text-red-300">
              {error}
            </div>
            <div className="flex justify-end">
              <Button
                type="button"
                variant="ghost"
                onClick={closeModal}
                className="w-full rounded-3xl px-6 sm:w-auto"
              >
                {t('cancel')}
              </Button>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}
