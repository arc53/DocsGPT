import { Check } from 'lucide-react';
import { useState } from 'react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge, badgeVariantNames } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { CodeBlock } from '@/components/ui/code-block';

import { Example, Section } from '../shared';
import ToastStackDemo from './recipes/ToastStackDemo';

export default function BadgeSection() {
  const [noticeOpen, setNoticeOpen] = useState(true);
  const [filters, setFilters] = useState(['Carrier contracts', 'Failed runs']);
  return (
    <Section
      id="badges"
      title="Badges, toasts & notices"
      intro="Status meaning comes from the four status tokens. Pills are Badge. A field error is FormField error; a result inside an open modal, or a notice to read before acting, is an Alert; anything else the user did is a toast in the bottom-right corner."
    >
      <Example title="Badge variants" code='<Badge variant="success">'>
        <div className="flex flex-wrap items-center gap-2">
          {badgeVariantNames.map((variant) => (
            <Badge key={variant} variant={variant}>
              {variant}
            </Badge>
          ))}
          <Badge variant="success">
            <Check />
            With icon
          </Badge>
        </div>
      </Example>
      <Example
        title="Removable chip"
        code='<Badge onRemove removeLabel="Remove filter: …"> (a named 24px X button; never inside another button, so not in a MultiSelect trigger)'
      >
        <div className="flex flex-wrap items-center gap-2">
          {filters.map((filter) => (
            <Badge
              key={filter}
              onRemove={() =>
                setFilters((current) => current.filter((f) => f !== filter))
              }
              removeLabel={`Remove filter: ${filter}`}
            >
              {filter}
            </Badge>
          ))}
          {filters.length < 2 && (
            <Button
              variant="link"
              size="inline"
              onClick={() => setFilters(['Carrier contracts', 'Failed runs'])}
            >
              Reset filters
            </Button>
          )}
        </div>
      </Example>
      <Example
        title="Toasts"
        code='<ToastViewport> (one, in App.tsx) > <Toast><ToastHeader variant="default | success | warning | destructive | info"><ToastTitle wrap?> · <ToastItem icon? label meta><ToastStatus status/> · <ToastMessage variant="default | destructive" size>'
      >
        <ToastStackDemo />
      </Example>
      <Example
        title="Inline notices (forms and modals only)"
        code='<Alert variant="success | warning | info | destructive"> draws its own icon · variant is required · never pass an icon child · icon={null} drops it'
      >
        <div className="flex flex-col gap-3">
          <Alert variant="success">
            <AlertTitle>Connector synced</AlertTitle>
            <AlertDescription>
              SharePoint finished 12 minutes ago with no changes.
            </AlertDescription>
          </Alert>
          <Alert variant="warning">
            <AlertTitle>Token expires in 3 days</AlertTitle>
            <AlertDescription>
              Reconnect before Friday to keep the nightly sync running.
            </AlertDescription>
          </Alert>
          <Alert variant="info">
            <AlertTitle>Indexing in progress</AlertTitle>
            <AlertDescription>
              Answers may miss the newest documents until it finishes.
            </AlertDescription>
          </Alert>
          <Alert variant="destructive">
            <AlertTitle>Connector unreachable</AlertTitle>
            <AlertDescription>
              The SharePoint token expired. Reconnect to resume syncing.
            </AlertDescription>
          </Alert>
          <Alert variant="destructive">
            <AlertDescription>
              Failed to regenerate the token. Please try again.
            </AlertDescription>
          </Alert>
          <Alert variant="warning" className="max-w-md">
            <AlertDescription>
              Copy the token now and store it somewhere safe. For security
              reasons it won&apos;t be shown again.
            </AlertDescription>
          </Alert>
          <Alert variant="destructive" icon={null}>
            <CodeBlock surface="bare" tone="destructive" maxHeight="sm">
              {
                'TimeoutError: carrier-rates MCP server did not answer in 30s\n  at callTool (lookup_lane_rates)'
              }
            </CodeBlock>
          </Alert>
        </div>
      </Example>
      <Example
        title="Static note"
        code='<Alert variant="info" role="note"> (not announced; a bg-muted well is for assets, not notes)'
      >
        <Alert variant="info" role="note" className="max-w-md">
          <AlertDescription>
            Schedules run in the agent owner&apos;s timezone, Europe/Berlin.
          </AlertDescription>
        </Alert>
      </Example>
      <Example
        title="Dismissible notice"
        code='<Alert variant="info" onClose> (a notice floating over a canvas; the X is labelled t("close"))'
      >
        {noticeOpen ? (
          <Alert
            variant="info"
            className="max-w-md"
            onClose={() => setNoticeOpen(false)}
          >
            <AlertDescription>
              Drag a node from the palette to add a step to this workflow.
            </AlertDescription>
          </Alert>
        ) : (
          <Button
            variant="link"
            size="inline"
            onClick={() => setNoticeOpen(true)}
          >
            Show the notice again
          </Button>
        )}
      </Example>
    </Section>
  );
}
