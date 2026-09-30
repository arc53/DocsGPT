import {
  Check,
  CircleAlert,
  TriangleAlert,
  Clock,
  Mail,
  Search,
  Trash2,
  Info,
} from 'lucide-react';
import { useState } from 'react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge, badgeVariantNames } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

import { Example, Section } from '../shared';
import ToastStackDemo from './recipes/ToastStackDemo';

export default function BadgeSection() {
  const [noticeOpen, setNoticeOpen] = useState(true);
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
        title="Toasts"
        code='<ToastViewport> (one, in App.tsx) > <Toast><ToastHeader variant="default | success | warning | destructive | info"><ToastTitle wrap?> · <ToastItem icon? label meta><ToastStatus status/> · <ToastMessage variant="default | destructive" size>'
      >
        <ToastStackDemo />
      </Example>
      <Example
        title="Inline notices (forms and modals only)"
        code='<Alert variant="default (= neutral) | success | warning | info | destructive">'
      >
        <div className="flex flex-col gap-3">
          <Alert>
            <Mail />
            <AlertTitle>Index rebuilt</AlertTitle>
            <AlertDescription>
              All 1,204 chunks were re-embedded with the new model.
            </AlertDescription>
          </Alert>
          <Alert variant="success">
            <Check />
            <AlertTitle>Connector synced</AlertTitle>
            <AlertDescription>
              SharePoint finished 12 minutes ago with no changes.
            </AlertDescription>
          </Alert>
          <Alert variant="warning">
            <Clock />
            <AlertTitle>Token expires in 3 days</AlertTitle>
            <AlertDescription>
              Reconnect before Friday to keep the nightly sync running.
            </AlertDescription>
          </Alert>
          <Alert variant="info">
            <Search />
            <AlertTitle>Indexing in progress</AlertTitle>
            <AlertDescription>
              Answers may miss the newest documents until it finishes.
            </AlertDescription>
          </Alert>
          <Alert variant="destructive">
            <Trash2 />
            <AlertTitle>Connector unreachable</AlertTitle>
            <AlertDescription>
              The SharePoint token expired. Reconnect to resume syncing.
            </AlertDescription>
          </Alert>
          <Alert variant="destructive">
            <CircleAlert />
            <AlertDescription>
              Failed to regenerate the token. Please try again.
            </AlertDescription>
          </Alert>
          <Alert variant="warning" className="max-w-md">
            <TriangleAlert />
            <AlertDescription>
              Copy the token now and store it somewhere safe. For security
              reasons it won&apos;t be shown again.
            </AlertDescription>
          </Alert>
        </div>
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
            <Info />
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
