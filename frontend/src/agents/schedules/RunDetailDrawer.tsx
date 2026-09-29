import { useTranslation } from 'react-i18next';

import { Card } from '@/components/ui/card';
import {
  DescriptionItem,
  DescriptionList,
} from '@/components/ui/description-list';
import { SectionHeader } from '@/components/ui/section-header';
import { PanelBody, PanelHeader, SidePanel } from '@/components/ui/side-panel';
import { formatDateTime } from '../../utils/dateTimeUtils';
import type { ScheduleRun } from '../types/schedule';
import ScheduleStatusBadge from './StatusBadge';

export type RunDetailDrawerProps = {
  run: ScheduleRun | null;
  onClose: () => void;
};

const formatTimestamp = (value?: string | null): string => {
  return value ? formatDateTime(value) : '—';
};

/** Side sheet with a single run's output / error (terminal-state only). */
export default function RunDetailDrawer({
  run,
  onClose,
}: RunDetailDrawerProps) {
  const { t } = useTranslation();
  if (!run) return null;
  return (
    <SidePanel
      open
      onOpenChange={(open) => !open && onClose()}
      aria-describedby={undefined}
    >
      <PanelHeader title={t('agents.schedules.runDetails.title')} />
      <PanelBody>
        <DescriptionList size="sm">
          <DescriptionItem label={t('agents.schedules.runDetails.status')}>
            <ScheduleStatusBadge status={run.status} />
          </DescriptionItem>
          <DescriptionItem
            label={t('agents.schedules.runDetails.scheduledFor')}
          >
            {formatTimestamp(run.scheduled_for)}
          </DescriptionItem>
          <DescriptionItem label={t('agents.schedules.runDetails.started')}>
            {formatTimestamp(run.started_at)}
          </DescriptionItem>
          <DescriptionItem label={t('agents.schedules.runDetails.finished')}>
            {formatTimestamp(run.finished_at)}
          </DescriptionItem>
          <DescriptionItem label={t('agents.schedules.runDetails.tokens')}>
            {t('agents.schedules.runDetails.tokensValue', {
              prompt: run.prompt_tokens,
              generated: run.generated_tokens,
            })}
          </DescriptionItem>
          <DescriptionItem label={t('agents.schedules.runDetails.trigger')}>
            {t(`agents.schedules.trigger.${run.trigger_source}`, {
              defaultValue: run.trigger_source,
            })}
          </DescriptionItem>
        </DescriptionList>
        {run.error && (
          <section className="flex flex-col gap-1">
            <SectionHeader
              as="h3"
              size="xs"
              tone="destructive"
              title={
                run.error_type
                  ? t('agents.schedules.runDetails.errorWithType', {
                      type: run.error_type,
                    })
                  : t('agents.schedules.runDetails.error')
              }
            />
            <Card variant="filled" padding="sm">
              <div className="scrollbar-overlay max-h-48 overflow-y-auto">
                <pre className="font-mono text-xs wrap-break-word whitespace-pre-wrap">
                  {run.error}
                </pre>
              </div>
            </Card>
          </section>
        )}
        {run.output && (
          <section className="flex min-h-0 flex-1 flex-col gap-1">
            <SectionHeader
              as="h3"
              size="xs"
              title={
                <>
                  {t('agents.schedules.runDetails.output')}
                  {run.output_truncated && (
                    <span className="text-muted-foreground ml-1 text-xs">
                      {t('agents.schedules.runDetails.truncated')}
                    </span>
                  )}
                </>
              }
            />
            <Card
              variant="filled"
              padding="sm"
              className="min-h-0 flex-1 overflow-y-auto"
            >
              <pre className="font-mono text-xs wrap-break-word whitespace-pre-wrap">
                {run.output}
              </pre>
            </Card>
          </section>
        )}
      </PanelBody>
    </SidePanel>
  );
}
