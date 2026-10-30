import { ArrowRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
  DescriptionItem,
  DescriptionList,
} from '@/components/ui/description-list';
import { ListRow, ListRows } from '@/components/ui/list-row';
import { SectionHeader } from '@/components/ui/section-header';
import {
  PanelBody,
  PanelFooter,
  PanelHeader,
  SidePanel,
} from '@/components/ui/side-panel';

import { formatDateTime } from '../../utils/dateTimeUtils';
import { formatRunTime } from '../format';
import { eventTitle } from './labels';
import type { SyncEvent } from './types';

const KNOWLEDGE_PATH = '/settings/knowledge';
const CONNECTORS_PATH = '/settings/connectors';

export type SyncPanelProps = {
  event: SyncEvent;
  onClose: () => void;
};

/**
 * The calendar's panel for a knowledge sync: when the batch runs, how it
 * repeats, and each of its sources with when it last synced or that it needs
 * its connection reconnected. There is no Run now: sources sync one by one
 * from Knowledge.
 */
export default function SyncPanel({ event, onClose }: SyncPanelProps) {
  const { t } = useTranslation();
  return (
    <SidePanel
      open
      onOpenChange={(open) => !open && onClose()}
      aria-describedby={undefined}
    >
      <PanelHeader
        title={eventTitle(event, t)}
        description={`${t('activity.kind.ingest')} · ${formatDateTime(event.at)}`}
        actions={
          <Badge variant="default">
            {t('activity.calendar.state.planned')}
          </Badge>
        }
      />
      <PanelBody>
        <DescriptionList size="sm">
          <DescriptionItem label={t('activity.calendar.when')}>
            {formatDateTime(event.at)}
          </DescriptionItem>
          <DescriptionItem label={t('activity.calendar.repeats')}>
            {t(`activity.calendar.syncRepeats.${event.frequency}`)}
          </DescriptionItem>
        </DescriptionList>
        <section className="flex flex-col gap-2">
          <SectionHeader
            as="h3"
            size="xs"
            title={t('activity.calendar.sources')}
            count={event.sources.length}
          />
          <Card variant="subtle" padding="none" className="overflow-hidden">
            <ListRows>
              {event.sources.map((source) => (
                <ListRow
                  key={source.id}
                  title={source.name}
                  trailing={
                    source.blocked ? (
                      <span className="flex items-center gap-2">
                        <span className="text-warning text-xs font-medium">
                          {t('activity.calendar.needsReconnecting')}
                        </span>
                        <Button
                          size="sm"
                          variant="outline"
                          shape="pill"
                          asChild
                        >
                          <Link to={CONNECTORS_PATH}>
                            {t('activity.now.reconnectAction')}
                          </Link>
                        </Button>
                      </span>
                    ) : (
                      <span className="text-muted-foreground text-xs">
                        {source.last_synced_at
                          ? t('activity.calendar.lastSynced', {
                              time: formatRunTime(source.last_synced_at),
                              interpolation: { escapeValue: false },
                            })
                          : t('activity.calendar.notSyncedYet')}
                      </span>
                    )
                  }
                />
              ))}
            </ListRows>
          </Card>
        </section>
      </PanelBody>
      <PanelFooter>
        <Button shape="pill" asChild>
          <Link to={KNOWLEDGE_PATH}>
            {t('activity.calendar.openKnowledge')}
            <ArrowRight aria-hidden />
          </Link>
        </Button>
      </PanelFooter>
    </SidePanel>
  );
}
