import {
  MoreHorizontal,
  Pencil,
  Bot,
  ChevronRight,
  Calendar as CalendarIcon,
  Database,
  FileText,
  Globe,
  Link2,
  Cloud,
  Book,
  GitBranch,
  MessageSquare,
  Users,
  Workflow,
} from 'lucide-react';
import { useState } from 'react';
import { Avatar } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DescriptionItem,
  DescriptionList,
} from '@/components/ui/description-list';
import { EmptyState } from '@/components/ui/empty-state';
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { IconButton } from '@/components/ui/icon-button';
import { ListRow, ListRows } from '@/components/ui/list-row';
import { LoadingState } from '@/components/ui/loading-state';
import { OptionCard } from '@/components/ui/option-card';
import { Pagination } from '@/components/ui/pagination';
import { formatCount } from '../../utils/dateTimeUtils';
import { Switch } from '@/components/ui/switch';
import { Example, Section } from '../shared';

const SOURCE_TYPES = [
  ['Upload file', FileText],
  ['Crawler', Globe],
  ['Link', Link2],
  ['GitHub', GitBranch],
  ['Reddit', MessageSquare],
  ['Google Drive', Cloud],
  ['Amazon S3', Database],
  ['New wiki', Book],
] as const;

export default function CardSection() {
  const [pagerPage, setPagerPage] = useState(2);
  const [pagerSize, setPagerSize] = useState(12);
  const [agentType, setAgentType] = useState<'classic' | 'workflow'>('classic');
  const [toolOn, setToolOn] = useState(false);
  const [sourceType, setSourceType] = useState<string>('Upload file');
  return (
    <Section
      id="cards"
      title="Cards"
      intro="One card, three surfaces. outline is the bordered default; filled is for tiles on a card-coloured page; subtle is a bordered box on a muted page. Interactive cards are the whole target."
    >
      <Example
        title="Entity cards"
        code='<Card variant="outline | filled"> + CardHeader / CardTitle / CardAction / CardFooter · a truncating or clamped string CardTitle sets its own title'
      >
        <div className="grid gap-4 md:grid-cols-3">
          <Card variant="filled">
            <CardHeader>
              <CardTitle className="line-clamp-2">
                Doc 1 - Tender Guidance and Checklist.docx
              </CardTitle>
              <CardAction>
                <IconButton
                  size="icon-xs"
                  variant="ghost-muted"
                  label="More"
                  icon={MoreHorizontal}
                />
              </CardAction>
            </CardHeader>
            <CardFooter className="flex-col items-start gap-1">
              <span className="flex items-center gap-1">
                <CalendarIcon className="size-3" /> 11/08/2026, 16:44
              </span>
              <span className="flex items-center gap-1">
                <Database className="size-3" /> 1.8k tokens
              </span>
            </CardFooter>
          </Card>
          <Card variant="filled">
            <CardHeader>
              <div className="flex flex-col gap-1">
                <CardTitle>Arc53</CardTitle>
                <Badge variant="neutral">GraphRAG</Badge>
              </div>
              <CardAction>
                <IconButton
                  size="icon-xs"
                  variant="ghost-muted"
                  label="More"
                  icon={MoreHorizontal}
                />
              </CardAction>
            </CardHeader>
            <CardFooter className="flex-col items-start gap-1">
              <span className="flex items-center gap-1">
                <CalendarIcon className="size-3" /> 29/06/2026, 05:22
              </span>
              <span className="flex items-center gap-1">
                <Database className="size-3" /> 20.19k tokens
              </span>
            </CardFooter>
          </Card>
          <Card variant="filled">
            <CardHeader>
              <span className="bg-muted-foreground/15 text-foreground flex size-8 items-center justify-center rounded-md">
                <FileText className="size-4" />
              </span>
              <CardAction>
                <IconButton
                  size="icon-xs"
                  variant="ghost-muted"
                  label="More"
                  icon={MoreHorizontal}
                />
              </CardAction>
            </CardHeader>
            <CardContent className="flex flex-col gap-1">
              <CardTitle>Notepad</CardTitle>
              <CardDescription>
                Single note. Supports viewing, overwriting, string replacement.
              </CardDescription>
            </CardContent>
            <CardFooter className="justify-end">
              <Switch
                checked={toolOn}
                onCheckedChange={setToolOn}
                aria-label="Enable tool"
              />
            </CardFooter>
          </Card>
        </div>
      </Example>
      <Example
        title="Bordered surfaces"
        code='<Card> (outline) · <Card interactive asChild><Link/></Card> · <Card padding="sm"> · <Card variant="filled" interactive="within"> + stretched <button>'
      >
        <div className="grid gap-4 md:grid-cols-2">
          <Card interactive asChild>
            <a href="#cards">
              <CardHeader>
                <div className="flex items-center gap-3">
                  <Avatar size="default" shape="square" variant="muted">
                    A
                  </Avatar>
                  <CardTitle>Arc</CardTitle>
                </div>
                <CardAction className="flex items-center gap-2">
                  <Badge variant="neutral">admin</Badge>
                  <span className="text-muted-foreground">›</span>
                </CardAction>
              </CardHeader>
              <CardDescription className="italic">
                No description
              </CardDescription>
              <CardFooter>
                <Users className="size-3" /> 3 members · 3 shared
              </CardFooter>
            </a>
          </Card>
          <Card variant="filled" padding="lg" interactive="within">
            <button
              type="button"
              className="text-left outline-none after:absolute after:inset-0 after:rounded-2xl"
            >
              <CardTitle>Q3 carrier tenders</CardTitle>
            </button>
            <CardDescription size="xs">
              A stretched button opens the source; the badge and menu are
              siblings above it.
            </CardDescription>
            <div className="relative z-10 flex items-center gap-2">
              <Badge variant="warning">Reconnect</Badge>
              <Button variant="outline" size="sm" shape="pill">
                Reconnect
              </Button>
            </div>
          </Card>
          <Card>
            <CardHeader>
              <div className="flex items-start gap-3">
                <Avatar size="lg" shape="circle" imgClassName="size-full" />
                <div className="flex flex-col gap-1">
                  <CardTitle>DocsGPT New Contact Responder</CardTitle>
                  <CardDescription className="line-clamp-2">
                    This agent processes notifications about new contact form
                    submissions, extracts the name and email address, then
                    drafts a personalised welcome.
                  </CardDescription>
                </div>
              </div>
              <CardAction>
                <Button size="sm" variant="outline" shape="pill">
                  <Pencil />
                  Edit
                </Button>
              </CardAction>
            </CardHeader>
          </Card>
          <div className="grid grid-cols-2 items-start gap-3">
            <Card padding="sm" className="gap-1">
              <CardDescription>Run success</CardDescription>
              <span className="text-xl font-semibold">—</span>
            </Card>
            <Card padding="sm" className="gap-1">
              <CardDescription>Feedback</CardDescription>
              <span className="text-xl font-semibold">+0 / -0</span>
            </Card>
          </div>
          <Card padding="sm">
            <CardHeader className="items-center">
              <CardTitle>Token usage</CardTitle>
              <CardAction className="flex items-center gap-2">
                <span className="text-muted-foreground text-xs">
                  Background tokens
                </span>
                <Switch aria-label="Background tokens" />
              </CardAction>
            </CardHeader>
            <CardContent>
              <div className="bg-muted/40 flex h-24 items-end justify-around rounded-lg px-4 pb-2">
                <span className="bg-chart-1 h-6 w-3 rounded-sm" />
                <span className="bg-chart-1 h-16 w-3 rounded-sm" />
                <span className="bg-chart-2 h-10 w-3 rounded-sm" />
                <span className="bg-chart-1 h-3 w-3 rounded-sm" />
              </div>
            </CardContent>
          </Card>
        </div>
      </Example>
      <Example
        title="Subtle surface and paddings"
        code='<Card variant="subtle"> a place on the page · tone="destructive" · padding="lg" · padding="none"'
      >
        <div className="grid items-start gap-4 md:grid-cols-2">
          <Card variant="subtle" padding="lg">
            <CardTitle>Subtle</CardTitle>
            <CardDescription>
              subtle is a place: a bordered panel on the page background (form
              sections, charts, logs); lg pads it 24px.
            </CardDescription>
          </Card>
          <Card tone="destructive" padding="lg">
            <CardTitle>Danger zone</CardTitle>
            <CardDescription>
              tone=&quot;destructive&quot;: the status soft fill and border, for
              danger zones and a red stat tile.
            </CardDescription>
          </Card>
          <Card padding="none" className="overflow-hidden">
            <div className="bg-muted/40 flex h-20 items-center justify-center">
              <FileText className="text-muted-foreground size-6" />
            </div>
            <CardContent className="px-4 pb-4">
              <CardTitle>QBR report.html</CardTitle>
              <CardDescription>
                padding=&quot;none&quot;: the preview bleeds to the edge.
              </CardDescription>
            </CardContent>
          </Card>
        </div>
      </Example>
      <Example
        title="Picker tiles"
        code="<OptionCard icon title description? selected onClick>"
      >
        <div className="flex flex-col gap-6">
          <div className="grid gap-3 sm:grid-cols-2" role="radiogroup">
            <OptionCard
              icon={<Bot />}
              title="Classic Agent"
              description="A standard AI agent with a single model, tools and knowledge sources."
              selected={agentType === 'classic'}
              onClick={() => setAgentType('classic')}
            />
            <OptionCard
              icon={<Workflow />}
              title="Workflow Agent"
              description="Multi-step workflows with different models, conditions and state."
              selected={agentType === 'workflow'}
              onClick={() => setAgentType('workflow')}
            />
          </div>
          <div
            className="grid gap-3 sm:grid-cols-2 md:grid-cols-3"
            role="radiogroup"
          >
            {SOURCE_TYPES.map(([label, Icon]) => (
              <OptionCard
                key={label}
                icon={<Icon />}
                title={label}
                selected={sourceType === label}
                onClick={() => setSourceType(label)}
              />
            ))}
          </div>
        </div>
      </Example>
      <Example
        title="Identity rows"
        code='<ListRows><ListRow leading title description trailing interactive asChild> · a string title/description sets its own title · icon tile: <Avatar size="sm" shape="square" variant="icon">'
      >
        <Card padding="none" className="overflow-hidden">
          <ListRows>
            <ListRow
              leading={
                <Avatar size="sm" shape="circle" variant="muted">
                  L
                </Avatar>
              }
              title="lena.fischer@meridianfreight.com"
              description="Added manually"
              trailing={<Badge variant="default">admin</Badge>}
            />
            <ListRow
              leading={
                <Avatar size="sm" shape="square" variant="icon">
                  <FileText className="size-4" />
                </Avatar>
              }
              title="Carrier contracts 2026"
              description="Source"
              trailing={<Badge variant="neutral">viewer</Badge>}
            />
            <ListRow
              interactive
              asChild
              title="Sources"
              trailing={
                <ChevronRight className="text-muted-foreground size-4" />
              }
            >
              <button type="button" />
            </ListRow>
          </ListRows>
        </Card>
      </Example>
      <Example
        title="Dense rows (side panel)"
        code='<ul className="-mx-2"><ListRow size="sm" interactive asChild leading title description>'
      >
        <ul className="-mx-2 flex max-w-80 flex-col">
          {[
            ['Oslo Freight Terminal', 'operates · ships via', 'bg-chart-2'],
            ['Meridian Freight Group', 'contracted by', 'bg-chart-1'],
          ].map(([name, meta, dot]) => (
            <ListRow
              key={name}
              size="sm"
              interactive
              asChild
              leading={
                <span
                  aria-hidden="true"
                  className={`mt-1.5 size-2 shrink-0 rounded-full ${dot}`}
                />
              }
              title={name}
              description={meta}
            >
              <button type="button" />
            </ListRow>
          ))}
        </ul>
      </Example>
      <Example
        title="Key/value rows"
        code='<DescriptionList layout="columns | justified" size="sm | xs"><DescriptionItem label mono>'
      >
        <div className="grid items-start gap-6 md:grid-cols-2">
          <DescriptionList>
            <DescriptionItem label="Status">
              <Badge variant="success">Success</Badge>
            </DescriptionItem>
            <DescriptionItem label="Started">24/09/2026, 09:00</DescriptionItem>
            <DescriptionItem label="Endpoint" mono>
              https://api.meridianfreight.example/v2/carriers/renewals
            </DescriptionItem>
          </DescriptionList>
          <DescriptionList layout="justified">
            <DescriptionItem label="Last used">3 minutes ago</DescriptionItem>
            <DescriptionItem label="Tokens">1,204</DescriptionItem>
          </DescriptionList>
        </div>
      </Example>
      <Example
        title="Pager"
        code="<Pagination page pageSize total onPageChange onPageSizeChange? pageSizeOptions? pageSizeLabel? rangeLabel?>"
      >
        <div className="flex flex-col gap-4">
          <Pagination
            page={pagerPage}
            pageSize={pagerSize}
            total={86}
            onPageChange={setPagerPage}
            onPageSizeChange={(size) => {
              setPagerSize(size);
              setPagerPage(1);
            }}
            rangeLabel={({ from, to, total }) =>
              `${from}–${to} of ${total} sources`
            }
          />
          <Pagination
            page={pagerPage}
            pageSize={25}
            total={1024}
            onPageChange={setPagerPage}
            rangeLabel={({ from, to, total }) =>
              `${from}–${to} of ${formatCount(total)} users`
            }
          />
          {/* Under 36rem of its own width the pager goes compact. */}
          <div className="max-w-sm">
            <Pagination
              page={pagerPage}
              pageSize={25}
              total={342}
              onPageChange={setPagerPage}
            />
          </div>
        </div>
      </Example>
      <Example
        title="Empty, loading and failed"
        code="<EmptyState size tone illustration action onRetry> · <LoadingState fill label>"
      >
        <div className="grid items-center gap-6 md:grid-cols-3">
          <EmptyState size="sm" title="No existing Sources" />
          <EmptyState
            tone="destructive"
            size="sm"
            illustration="none"
            title="Failed to load usage."
            onRetry={() => undefined}
          />
          <LoadingState fill="block" label="Converting..." />
        </div>
      </Example>
    </Section>
  );
}
