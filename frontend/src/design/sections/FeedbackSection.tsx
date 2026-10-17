import { Copy, Search, Settings, X, Trash2, Undo2, Redo2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { IconButton } from '@/components/ui/icon-button';
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from '@/components/ui/message-scroller';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { Spinner } from '@/components/ui/spinner';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { Example, Section } from '../shared';

export default function FeedbackSection() {
  return (
    <Section
      id="feedback"
      title="Feedback & loading"
      intro="IconButton names every icon-only button and gives it a tooltip, so no button sets title; Spinner and Skeleton replace the hand-drawn loaders; Progress replaces width-percent divs."
    >
      <Example
        title="Icon buttons with tooltips"
        code='<IconButton label icon hint? side="bottom" (header) | "top" (default) variant size>'
      >
        <div className="flex flex-col gap-6">
          <div className="border-border flex items-center justify-between border-b pb-3">
            <span className="text-sm font-medium">Run details</span>
            <div className="flex items-center gap-1">
              <IconButton
                variant="ghost-muted"
                side="bottom"
                label="Search runs"
                icon={Search}
              />
              <IconButton
                variant="ghost-muted"
                side="bottom"
                label="Settings"
                icon={Settings}
              />
              <IconButton
                variant="ghost-muted"
                side="bottom"
                label="Close"
                icon={X}
              />
            </div>
          </div>
          <div className="flex flex-col gap-2">
            <p className="text-foreground max-w-md text-sm">
              The renewal summary for Halvorsen Logistics lists three lanes
              above target cost.
            </p>
            <div className="flex items-center gap-1">
              <IconButton
                variant="ghost-muted"
                size="icon-sm"
                shape="pill"
                label="Copy"
                icon={Copy}
              />
              <IconButton
                variant="ghost-muted"
                size="icon-sm"
                shape="pill"
                label="Undo"
                hint="Undo (Ctrl+Z)"
                icon={Undo2}
              />
              <IconButton
                variant="ghost-muted"
                size="icon-sm"
                shape="pill"
                label="Redo"
                hint="Redo (Ctrl+Shift+Z)"
                icon={Redo2}
              />
              <IconButton
                variant="ghost-destructive"
                size="icon-sm"
                shape="pill"
                label="Delete"
                icon={Trash2}
              />
            </div>
          </div>
          <span className="text-muted-foreground text-xs">
            Header and toolbar buttons open below; buttons under text, in the
            composer and in rows open above. Toast close and collapse stay a
            plain Button with aria-label.
          </span>
        </div>
      </Example>
      <Example
        title="Tooltip on something else"
        code="<Tooltip><TooltipTrigger asChild>…</TooltipTrigger><TooltipContent>"
      >
        <div className="flex flex-wrap items-center gap-3">
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge variant="neutral">GraphRAG</Badge>
            </TooltipTrigger>
            <TooltipContent>
              Indexed as a knowledge graph; answers can follow relations between
              entities.
            </TooltipContent>
          </Tooltip>
          <span className="text-muted-foreground text-xs">
            hover or focus the controls
          </span>
        </div>
      </Example>
      <Example
        title="Spinner and skeleton"
        code='<Spinner size="xs | sm | default | lg"> · <Skeleton className="h-4 w-40"> · <Skeleton surface="muted"> in a filled Card'
      >
        <div className="grid items-start gap-8 md:grid-cols-2">
          <div className="flex items-center gap-6">
            <Spinner size="xs" />
            <Spinner size="sm" />
            <Spinner />
            <Spinner size="lg" />
            <span className="text-primary flex items-center gap-2 text-sm">
              <Spinner size="sm" /> inherits text colour
            </span>
          </div>
          <div className="flex items-center gap-4">
            <Skeleton className="size-10 rounded-full" />
            <div className="flex flex-1 flex-col gap-2">
              <Skeleton className="h-4 w-3/5" />
              <Skeleton className="h-3 w-4/5" />
              <Skeleton className="h-3 w-2/5" />
            </div>
          </div>
          <Card variant="filled" padding="lg" className="md:col-span-2">
            <Skeleton surface="muted" className="size-10 rounded-full" />
            <Skeleton surface="muted" className="h-4 w-2/5" />
            <Skeleton surface="muted" className="h-3 w-3/5" />
          </Card>
        </div>
      </Example>
      <Example
        title="Progress"
        code='<Progress value={62} variant="success" size="sm">'
      >
        <div className="grid gap-5 md:grid-cols-2">
          <div className="flex flex-col gap-2">
            <div className="text-muted-foreground flex justify-between text-xs">
              <span>Indexing 1,204 chunks</span>
              <span>62%</span>
            </div>
            <Progress value={62} />
          </div>
          <div className="flex flex-col gap-2">
            <div className="text-muted-foreground flex justify-between text-xs">
              <span>Monthly quota</span>
              <span>91%</span>
            </div>
            <Progress value={91} variant="warning" />
          </div>
          <div className="flex flex-col gap-2">
            <div className="text-muted-foreground flex justify-between text-xs">
              <span>Run success</span>
              <span>100%</span>
            </div>
            <Progress value={100} variant="success" size="sm" />
          </div>
          <div className="flex flex-col gap-2">
            <div className="text-muted-foreground flex justify-between text-xs">
              <span>Guardrail blocks</span>
              <span>18%</span>
            </div>
            <Progress value={18} variant="destructive" />
          </div>
          <div className="flex flex-col gap-2">
            <div className="text-muted-foreground flex justify-between text-xs">
              <span>Re-embedding</span>
              <span>40%</span>
            </div>
            <Progress value={40} variant="info" />
          </div>
        </div>
      </Example>
      <Example
        title="Message scroller"
        code="<MessageScrollerProvider autoScroll><MessageScroller><MessageScrollerViewport><MessageScrollerContent><MessageScrollerItem messageId scrollAnchor?> · <MessageScrollerButton />"
      >
        <div className="border-border h-64 max-w-md overflow-hidden rounded-lg border">
          <MessageScrollerProvider autoScroll>
            <MessageScroller>
              <MessageScrollerViewport className="px-4 pt-4">
                <MessageScrollerContent className="gap-3 pb-4">
                  {[
                    'Which carriers renew this quarter?',
                    'Halvorsen Logistics, Nordhavn Freight and Baltic Line renew before 30 November.',
                    'Which of them are above target cost?',
                    'Two lanes on Halvorsen and one on Baltic Line are 6-9% above target.',
                    'Draft the renewal summary.',
                    'The summary is ready: three lanes to renegotiate, two to keep as they are.',
                  ].map((text, index) => (
                    <MessageScrollerItem
                      key={text}
                      messageId={`ds-m-${index}`}
                      scrollAnchor={index % 2 === 0}
                    >
                      <p
                        className={
                          index % 2 === 0
                            ? 'bg-answer-surface ml-auto w-fit max-w-[80%] rounded-2xl px-3 py-2 text-sm'
                            : 'text-foreground text-sm'
                        }
                      >
                        {text}
                      </p>
                    </MessageScrollerItem>
                  ))}
                </MessageScrollerContent>
              </MessageScrollerViewport>
              <MessageScrollerButton />
            </MessageScroller>
          </MessageScrollerProvider>
        </div>
      </Example>
    </Section>
  );
}
