import React from 'react';
import { useTranslation } from 'react-i18next';

import ViewOnlyNotice from '@/components/ViewOnlyNotice';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Collapsible, CollapsibleTrigger } from '@/components/ui/collapsible';

import { analyticsOf, isDefaultAnalytics } from '../analyticsConfig';
import type { AnalyticsConfig } from '../types';
import InsightsSettingsBody from './InsightsSettingsBody';

type AnalyticsSectionProps = {
  value?: AnalyticsConfig;
  onChange: (next: AnalyticsConfig) => void;
  /** A saved agent's id: the source folders need it. */
  agentId?: string;
  /** The server lets the decision model label conversations. */
  available: boolean;
  maxTopics: number;
  maxOverlapping: number;
  /** The caller can't save the agent: the settings show, read-only. */
  disabled?: boolean;
  token: string | null;
};

/**
 * The agent form's Insights section: a collapsible card around
 * `InsightsSettingsBody`, saved by the form's Save. A neutral "Off" sits
 * beside the title while the agent's insights are off (on is the default).
 * Not policy, so anyone who can save the agent changes it. Hidden while the
 * server has labelling off, unless the agent already has settings of its own
 * to see and change.
 */
export default function AnalyticsSection({
  value,
  onChange,
  agentId,
  available,
  maxTopics,
  maxOverlapping,
  disabled = false,
  token,
}: AnalyticsSectionProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = React.useState(false);
  const bodyId = React.useId();

  if (!available && isDefaultAnalytics(value)) return null;
  const enabled = analyticsOf(value).enabled;

  return (
    <Card
      variant="subtle"
      padding="lg"
      className="gap-5"
      data-testid="analytics-section"
    >
      {/* The card's gap-5 sits inside the body, so it folds away with it. */}
      <div>
        <div className="flex flex-wrap items-center gap-2">
          {/* The heading wraps the toggle: a button's children are
            presentational, so a heading inside it is lost to screen readers. */}
          <h2>
            <CollapsibleTrigger
              look="section"
              open={expanded}
              onOpenChange={setExpanded}
              controls={bodyId}
              data-testid="analytics-toggle"
            >
              {t('agents.form.sections.analytics')}
            </CollapsibleTrigger>
          </h2>
          {!enabled && (
            <Badge variant="neutral" data-testid="analytics-off-badge">
              {t('agents.form.analytics.off')}
            </Badge>
          )}
        </div>

        <Collapsible open={expanded} id={bodyId}>
          <div className="flex flex-col gap-5 pt-5">
            {disabled && <ViewOnlyNotice />}
            {!available && (
              <Alert variant="info" role="note">
                <AlertDescription>
                  {t('agents.form.analytics.serverOff')}
                </AlertDescription>
              </Alert>
            )}
            <InsightsSettingsBody
              value={value}
              onChange={onChange}
              agentId={agentId}
              maxTopics={maxTopics}
              maxOverlapping={maxOverlapping}
              disabled={disabled}
              token={token}
              // The source folders load once the section opens, with the
              // server's switch off too: hidden ones can still come back.
              active={expanded}
            />
          </div>
        </Collapsible>
      </div>
    </Card>
  );
}
