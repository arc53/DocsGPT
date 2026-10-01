import {
  ArrowRight,
  Check,
  Copy,
  ExternalLink,
  Mic,
  MoreHorizontal,
  Pencil,
  Pin,
  Play,
  Plus,
  Settings,
  SquarePen,
  ChevronDown,
  Book,
  MessageSquare,
  Trash2,
} from 'lucide-react';
import { useState } from 'react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import {
  Button,
  buttonSizeNames,
  buttonVariantNames,
} from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Collapsible, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Combobox } from '@/components/ui/combobox';
import { ActionMenu } from '@/components/ui/dropdown-menu';
import { IconButton } from '@/components/ui/icon-button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { NavTab } from '@/components/ui/tabs';
import { ToggleChip } from '@/components/ui/toggle-chip';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Example, Section } from '../shared';

// Link sizes have no height or padding; the Links example shows them.
const LINK_SIZES = new Set<string>(['inline', 'text']);

// Columns of the variant matrix: every text size in cva order. Icon sizes get
// their own row of IconButtons below.
const BUTTON_SIZES = buttonSizeNames.filter(
  (size) => !size.startsWith('icon') && !LINK_SIZES.has(size),
);

// Options for the Combobox trigger demo (the full picker is under Pickers).
const TRIGGER_TIMEZONES = [
  { value: 'Europe/London', label: 'Europe/London', hint: 'UTC+01:00' },
  { value: 'Europe/Berlin', label: 'Europe/Berlin', hint: 'UTC+02:00' },
  { value: 'America/Chicago', label: 'America/Chicago', hint: 'UTC−05:00' },
];

const ICON_SIZES = buttonSizeNames.filter(
  (size): size is Extract<typeof size, `icon${string}`> =>
    size.startsWith('icon'),
);

export default function ButtonSection() {
  const [sectionOpen, setSectionOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [range, setRange] = useState('30d');
  const [trackRange, setTrackRange] = useState('7d');
  const [days, setDays] = useState<string[]>(['mon', 'wed', 'fri']);
  const [agentFilter, setAgentFilter] = useState('all');
  const [runFilter, setRunFilter] = useState('all');
  const [stages, setStages] = useState<string[]>(['input', 'output']);
  const [capabilities, setCapabilities] = useState<string[]>(['tools']);
  return (
    <Section
      id="buttons"
      title="Buttons"
      intro="Pick a variant for meaning, a size for density and a shape for the surface it sits on. className is for placement only."
    >
      <Example title="Variants × sizes" code='<Button variant="…" size="…">'>
        <div className="overflow-x-auto">
          <div
            data-testid="button-matrix"
            className="grid min-w-2xl grid-cols-[8rem_repeat(var(--matrix-cols),auto)] items-center gap-x-6 gap-y-3"
            style={
              { '--matrix-cols': BUTTON_SIZES.length } as React.CSSProperties
            }
          >
            <span />
            {BUTTON_SIZES.map((size) => (
              <span
                key={size}
                className="text-muted-foreground font-mono text-xs"
              >
                {size}
              </span>
            ))}
            {buttonVariantNames.map((variant) => (
              <div key={variant} className="contents">
                <span className="text-muted-foreground font-mono text-xs">
                  {variant}
                </span>
                {BUTTON_SIZES.map((size) => (
                  <div key={size}>
                    <Button variant={variant} size={size}>
                      <Plus />
                      Add source
                    </Button>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      </Example>
      <Example
        title="Shapes"
        code='shape="pill" replaces rounded-3xl / rounded-full overrides'
      >
        <div className="flex flex-wrap items-center gap-3">
          <Button shape="pill">Send</Button>
          <Button shape="pill" size="lg">
            Get started
          </Button>
          <Button shape="pill" variant="outline-primary">
            Upgrade
          </Button>
          <Button shape="pill" variant="outline">
            <Settings />
            Configure
          </Button>
          <Button shape="pill" variant="secondary" size="sm">
            Filter
          </Button>
          <Button shape="pill" variant="ghost-muted" size="xs">
            Clear
          </Button>
          <Button shape="pill" variant="outline" size="sm">
            <Mic />
            Voice
          </Button>
        </div>
      </Example>
      <Example
        title="Sidebar rows"
        code='<Button variant="sidebar-item" aria-current={active ? "page" : undefined}>'
      >
        <div className="bg-sidebar flex w-64 flex-col gap-1 rounded-lg border py-2">
          <Button variant="sidebar-item" className="mx-4 w-auto">
            <Book className="text-muted-foreground size-5" />
            Sources
          </Button>
          <Button
            variant="sidebar-item"
            aria-current="page"
            className="mx-4 w-auto"
          >
            <Settings className="text-muted-foreground size-5" />
            Settings
          </Button>
          <Button variant="sidebar-item" className="mx-4 w-auto">
            <MessageSquare className="text-muted-foreground size-5" />
            Help
          </Button>
        </div>
      </Example>
      <Example
        title="Truncating a name in a Button"
        code='<Button className="min-w-0 shrink"><Avatar /><span className="truncate" title={name}>{name}</span><ChevronDown /></Button>'
      >
        <div className="flex w-64 items-center gap-1 rounded-md border p-1">
          <div className="flex min-w-0 flex-1">
            <Button variant="ghost" size="sm" className="min-w-0 shrink">
              <span
                className="truncate"
                title="Explain the difference between agents and workflows"
              >
                Explain the difference between agents and workflows
              </span>
              <ChevronDown className="text-muted-foreground" aria-hidden />
            </Button>
          </div>
          <IconButton
            label="New chat"
            variant="ghost-muted"
            size="icon"
            icon={SquarePen}
          />
        </div>
      </Example>
      <Example
        title="Combobox trigger"
        code='<Combobox> draws it: <Button variant="combobox" size="field" role="combobox"> + the rotating ChevronDown (MultiSelect shares it) · never hand-build the trigger'
      >
        <div className="flex max-w-md flex-col gap-3">
          <Combobox
            aria-label="Timezone"
            placeholder="Select a timezone…"
            searchPlaceholder="Search timezones"
            emptyText="No timezone found."
            options={TRIGGER_TIMEZONES}
            value={null}
            onValueChange={() => undefined}
          />
          <Combobox
            aria-label="Timezone"
            placeholder="Select a timezone…"
            searchPlaceholder="Search timezones"
            emptyText="No timezone found."
            options={TRIGGER_TIMEZONES}
            value="Europe/Berlin"
            onValueChange={() => undefined}
          />
        </div>
      </Example>
      <Example
        title="Form row (field height)"
        code='<Input shape="pill"> · <SelectTrigger size="field" shape="pill"> · <Button variant="combobox" size="field" shape="pill">'
      >
        <div className="flex max-w-md flex-col gap-3">
          <Input shape="pill" placeholder="Agent name" />
          <div className="flex gap-2">
            <Select defaultValue="default">
              <SelectTrigger size="field" shape="pill" className="flex-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="default">default</SelectItem>
                <SelectItem value="strict">strict</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="outline-primary" size="field" shape="pill">
              Add
            </Button>
          </div>
          <Button
            variant="combobox"
            size="field"
            shape="pill"
            data-placeholder=""
            className="w-full justify-start text-left"
          >
            <span className="truncate">Select sources</span>
          </Button>
        </div>
      </Example>
      <Example
        title="Links: in running text, standalone, with an icon, in a status Alert"
        code='size="text" (inherits size, weight, line-height; keeps primary) · size="inline" (14px medium) · a trailing ArrowRight / ExternalLink is 12px, set by the size (no size-3) · a leading icon sets size-4 · tone="current" (context colour)'
      >
        <div className="flex max-w-md flex-col gap-4">
          <p className="text-foreground text-base">
            The quarterly review for Halvorsen Logistics is ready. Open{' '}
            <Button variant="link" size="text" asChild>
              <a href="#buttons">QBR report.html</a>
            </Button>{' '}
            to see lane costs and the renewal summary.
          </p>
          <p className="text-muted-foreground text-xs">
            Fine-grained, with read access to Contents.{' '}
            <Button variant="link" size="text" asChild>
              <a href="#buttons">
                Create a token on GitHub
                <ExternalLink />
              </a>
            </Button>
          </p>
          <div className="flex flex-wrap items-center gap-6">
            <Button variant="link" size="inline">
              Browse all connectors
            </Button>
            <Button variant="link" size="inline">
              View all runs
              <ArrowRight />
            </Button>
            <Button variant="link" size="inline">
              <Plus className="size-4" />
              Add a carrier
            </Button>
          </div>
          <Alert variant="warning">
            <AlertDescription>
              This connector needs setup before agents can use it.{' '}
              <Button variant="link" size="text" tone="current" asChild>
                <a href="#buttons">Setup guide</a>
              </Button>
            </AlertDescription>
          </Alert>
        </div>
      </Example>
      <Example
        title="Route tabs"
        code='<nav><NavTab current={active}><Link to>…</Link></NavTab></nav> (aria-current="page"; not Radix Tabs)'
      >
        <nav aria-label="Agent pages" className="flex items-center">
          <NavTab current>
            <a href="#buttons">Overview</a>
          </NavTab>
          <NavTab>
            <a href="#buttons">Logs</a>
          </NavTab>
          <NavTab>
            <a href="#buttons">Schedules</a>
          </NavTab>
        </nav>
      </Example>
      <Example title="Loading" code="<Button loading={saving}>">
        <div className="flex flex-wrap items-center gap-3">
          <Button
            size="lg"
            shape="pill"
            loading={saving}
            onClick={() => {
              setSaving(true);
              window.setTimeout(() => setSaving(false), 1500);
            }}
          >
            Create token
          </Button>
          <Button variant="outline" size="lg" shape="pill" loading>
            Test connection
          </Button>
          <Button variant="destructive" loading>
            Delete team
          </Button>
          <span className="text-muted-foreground text-xs">
            Disabled, aria-busy, 16px spinner over the kept label; the width
            holds.
          </span>
        </div>
      </Example>
      <Example
        title="Section panel toggle"
        code='<Card><h2><CollapsibleTrigger look="section" open onOpenChange controls></h2> · <Collapsible id open> (Card draws the focus ring)'
      >
        <div className="max-w-md">
          <Card variant="subtle" padding="lg">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2>
                  <CollapsibleTrigger
                    look="section"
                    open={sectionOpen}
                    onOpenChange={setSectionOpen}
                    controls="ds-section-toggle"
                  >
                    Guardrails
                  </CollapsibleTrigger>
                </h2>
                <Badge variant="success">3 active</Badge>
                <Badge variant="destructive">1 needs setup</Badge>
              </div>
              <Collapsible id="ds-section-toggle" open={sectionOpen}>
                <p className="text-muted-foreground pt-3 text-sm">
                  Run the selected checks on this agent&apos;s runs.
                </p>
              </Collapsible>
            </div>
          </Card>
        </div>
      </Example>
      <Example
        title="Pressed toggles"
        code='variant={active ? "secondary" : "ghost-muted"}'
      >
        <div className="grid gap-4 md:grid-cols-3">
          {(['card', 'background', 'muted'] as const).map((surface) => (
            <div
              key={surface}
              className={
                surface === 'card'
                  ? 'bg-card flex items-center gap-2 rounded-lg border p-4'
                  : surface === 'background'
                    ? 'bg-background flex items-center gap-2 rounded-lg border p-4'
                    : 'bg-muted flex items-center gap-2 rounded-lg border p-4'
              }
            >
              <IconButton
                variant="ghost-muted"
                size="icon-sm"
                shape="pill"
                label="Copy"
                icon={Copy}
              />
              <IconButton
                variant="secondary"
                size="icon-sm"
                shape="pill"
                label="Copied"
                icon={Check}
              />
              <Button variant="secondary" size="xs" shape="pill">
                <Check />
                Copied
              </Button>
              <span className="text-muted-foreground text-xs">
                on {surface}
              </span>
            </div>
          ))}
        </div>
      </Example>
      <Example
        title="Toggle chips"
        code='<ToggleChip pressed onPressedChange size="xs | sm" locked? disabled?> (any of N in a wrapping row; aria-pressed; locked = on + Lock + aria-disabled, reason in title) · ToggleGroup for one of N'
      >
        <div className="flex flex-col gap-6">
          <div className="flex flex-col gap-2">
            <div
              role="group"
              aria-label="Guardrail stages"
              className="flex flex-wrap items-center gap-2"
            >
              {(
                [
                  ['input', 'Input'],
                  ['output', 'Output'],
                  ['tool', 'Tool calls'],
                ] as const
              ).map(([id, label]) => (
                <ToggleChip
                  key={id}
                  pressed={stages.includes(id)}
                  onPressedChange={(on) =>
                    setStages((current) =>
                      on
                        ? [...current, id]
                        : current.filter((stage) => stage !== id),
                    )
                  }
                >
                  {label}
                </ToggleChip>
              ))}
              <ToggleChip
                pressed
                locked
                title="Required by your administrator for every agent"
              >
                PII redaction
              </ToggleChip>
              <ToggleChip pressed={false} disabled>
                Retrieval
              </ToggleChip>
            </div>
            <span className="text-muted-foreground text-xs">
              xs (dense panels): on, off, locked, disabled
            </span>
          </div>
          <div className="flex flex-col gap-2">
            <div
              role="group"
              aria-label="Model capabilities"
              className="flex flex-wrap items-center gap-2"
            >
              {(
                [
                  ['tools', 'Tool use'],
                  ['vision', 'Images'],
                  ['json', 'Structured output'],
                ] as const
              ).map(([id, label]) => {
                const on = capabilities.includes(id);
                return (
                  <ToggleChip
                    key={id}
                    size="sm"
                    pressed={on}
                    onPressedChange={(next) =>
                      setCapabilities((current) =>
                        next
                          ? [...current, id]
                          : current.filter((cap) => cap !== id),
                      )
                    }
                  >
                    {on && <Check />}
                    {label}
                  </ToggleChip>
                );
              })}
            </div>
            <span className="text-muted-foreground text-xs">
              sm (forms), a leading Check on the pressed chips
            </span>
          </div>
        </div>
      </Example>
      <Example
        title="Segmented control"
        code='<ToggleGroup type="single" value onValueChange={(v) => v && set(v)}> · the track is built in · sm 38px (forms, page toolbars) · size="xs" 36px (dense panels) · fill when it is the only control on its row · type="multiple" · <ToggleGroupItem count>'
      >
        <div className="flex flex-col gap-6">
          <div className="flex flex-wrap items-center gap-2">
            <ToggleGroup
              type="single"
              aria-label="Date range"
              value={range}
              onValueChange={(v) => v && setRange(v)}
            >
              <ToggleGroupItem value="7d">7d</ToggleGroupItem>
              <ToggleGroupItem value="30d">30d</ToggleGroupItem>
              <ToggleGroupItem value="90d">90d</ToggleGroupItem>
            </ToggleGroup>
            <span className="text-muted-foreground text-xs">
              sm, hugs (toolbar)
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <ToggleGroup
              type="single"
              size="xs"
              aria-label="Chart range"
              value={trackRange}
              onValueChange={(v) => v && setTrackRange(v)}
            >
              <ToggleGroupItem value="7d">7d</ToggleGroupItem>
              <ToggleGroupItem value="30d">30d</ToggleGroupItem>
              <ToggleGroupItem value="90d">90d</ToggleGroupItem>
            </ToggleGroup>
            <span className="text-muted-foreground text-xs">
              xs, hugs (dense panel)
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <ToggleGroup
              type="single"
              aria-label="Run status"
              value={runFilter}
              onValueChange={(v) => v && setRunFilter(v)}
            >
              <ToggleGroupItem value="all" count={1204}>
                All
              </ToggleGroupItem>
              <ToggleGroupItem value="failed" count={12}>
                Failed
              </ToggleGroupItem>
              <ToggleGroupItem value="flagged" count={3}>
                Flagged
              </ToggleGroupItem>
            </ToggleGroup>
            <span className="text-muted-foreground text-xs">
              sm, item count (muted on the selected item too)
            </span>
          </div>
          <div className="flex max-w-md flex-col gap-2">
            <ToggleGroup
              type="multiple"
              fill
              aria-label="Days of the week"
              value={days}
              onValueChange={setDays}
            >
              {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((day) => (
                <ToggleGroupItem key={day} value={day.toLowerCase()}>
                  {day}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <span className="text-muted-foreground text-xs">
              sm, fill (the only control on its row)
            </span>
          </div>
          <div className="flex flex-col gap-2">
            <nav aria-label="Agent filters" className="flex flex-wrap gap-1">
              {(
                [
                  ['all', 'All agents'],
                  ['mine', 'Mine'],
                  ['shared', 'Shared with me'],
                ] as const
              ).map(([id, label]) => (
                <Button
                  key={id}
                  asChild
                  variant={agentFilter === id ? 'outline' : 'ghost-muted'}
                  size="sm"
                  shape="pill"
                >
                  <a
                    href="#buttons"
                    aria-current={agentFilter === id ? 'page' : undefined}
                    onClick={(event) => {
                      event.preventDefault();
                      setAgentFilter(id);
                    }}
                  >
                    {label}
                  </a>
                </Button>
              ))}
            </nav>
            <span className="text-muted-foreground text-xs">
              Route links are not a ToggleGroup: Button asChild
              variant=&#123;active ? &apos;outline&apos; :
              &apos;ghost-muted&apos;&#125; size=&quot;sm&quot;
              shape=&quot;pill&quot; around each Link, aria-current on the
              current one.
            </span>
          </div>
        </div>
      </Example>
      <Example
        title="Icon buttons"
        code='<IconButton label="Edit" icon={Pencil} size="icon-xs" | "icon-sm" | "icon">'
      >
        <div className="flex flex-wrap items-center gap-6">
          {ICON_SIZES.map((size) => (
            <div key={size} className="flex flex-col items-center gap-2">
              <div className="flex items-center gap-2">
                <IconButton
                  size={size}
                  variant="default"
                  label="Add"
                  icon={Plus}
                />
                <IconButton
                  size={size}
                  variant="outline"
                  label="Edit"
                  icon={Pencil}
                />
                <IconButton
                  size={size}
                  variant="ghost-muted"
                  label="More"
                  icon={MoreHorizontal}
                />
                <IconButton
                  size={size}
                  variant="ghost-destructive"
                  shape="pill"
                  label="Delete"
                  icon={Trash2}
                />
              </div>
              <span className="text-muted-foreground font-mono text-xs">
                {size}
              </span>
            </div>
          ))}
        </div>
      </Example>
      <Example
        title="On an accent row"
        code='variant="ghost-on-accent" · "ghost-destructive-on-accent"'
      >
        <div className="flex flex-col gap-3">
          <div className="bg-accent text-accent-foreground flex w-80 items-center justify-between rounded-sm px-2 py-1.5 text-sm">
            <span>Carrier onboarding checklist</span>
            <div className="flex items-center gap-1">
              <IconButton
                size="icon-xs"
                variant="ghost-on-accent"
                label="Edit"
                icon={Pencil}
              />
              <IconButton
                size="icon-xs"
                variant="ghost-on-accent"
                label="Duplicate"
                icon={Copy}
              />
              <IconButton
                size="icon-xs"
                variant="ghost-destructive-on-accent"
                label="Delete"
                icon={Trash2}
              />
            </div>
          </div>
          <div className="bg-sidebar-accent flex h-9 w-80 items-center justify-between rounded-3xl pl-3 text-sm">
            <span>Vendor Due Diligence</span>
            <div className="flex items-center px-1.5">
              <IconButton
                size="icon-xs"
                variant="ghost-on-accent"
                label="Pin agent"
                icon={Pin}
              />
            </div>
          </div>
        </div>
      </Example>
      <Example
        title="Action menu"
        code='<ActionMenu options triggerLabel /> on a tile (separatorBefore on Delete) · size="toolbar" in a page header · trigger={<Button>} menuWidth="sm"'
      >
        <div className="flex flex-wrap items-center gap-6">
          <div className="bg-muted hover:bg-accent relative h-24 w-48 rounded-2xl p-4 text-sm">
            <span className="font-semibold">Vendor Due Diligence</span>
            <ActionMenu
              triggerLabel="Agent actions"
              className="absolute top-3 right-3"
              options={[
                { icon: Pencil, label: 'Edit', onClick: () => {} },
                { icon: Copy, label: 'Duplicate', onClick: () => {} },
                { icon: Pin, label: 'Pin agent', onClick: () => {} },
                {
                  icon: Trash2,
                  label: 'Delete',
                  variant: 'destructive',
                  separatorBefore: true,
                  onClick: () => {},
                },
              ]}
            />
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="field" shape="pill">
              <Play />
              Preview
            </Button>
            <Button size="field" shape="pill">
              Save
            </Button>
            <ActionMenu
              size="toolbar"
              triggerLabel="More actions"
              options={[
                { label: 'Access details', onClick: () => {} },
                { label: 'Share with team', onClick: () => {} },
              ]}
            />
          </div>
          {/* A labelled trigger instead of the three dots (a dialog footer). */}
          <ActionMenu
            trigger={
              <Button type="button" variant="outline" size="lg" shape="pill">
                Actions
                <ChevronDown />
              </Button>
            }
            menuWidth="sm"
            options={[
              { icon: Pencil, label: 'Rename', onClick: () => {} },
              { icon: Copy, label: 'Duplicate', onClick: () => {} },
              {
                icon: Trash2,
                label: 'Delete',
                variant: 'destructive',
                separatorBefore: true,
                onClick: () => {},
              },
            ]}
          />
        </div>
      </Example>
      <Example title="States" code="disabled · asChild">
        <div className="flex flex-wrap items-center gap-3">
          <Button disabled>Saving…</Button>
          <Button variant="outline" disabled>
            Disabled outline
          </Button>
          <Button variant="destructive">
            <Trash2 />
            Delete
          </Button>
          <Button variant="destructive-outline" size="sm">
            Remove
          </Button>
          <Button asChild variant="link">
            <a href="#buttons">Rendered as a link</a>
          </Button>
        </div>
      </Example>
    </Section>
  );
}
