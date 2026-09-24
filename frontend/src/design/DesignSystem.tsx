import {
  Check,
  Clock,
  Copy,
  Mail,
  Mic,
  Moon,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  Settings,
  Bot,
  ChevronDown,
  ChevronRight,
  ChevronsUpDown,
  X,
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
  Sun,
  Trash2,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Avatar } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb';
import { Button } from '@/components/ui/button';
import { Dropzone } from '@/components/ui/dropzone';
import { Calendar } from '@/components/ui/calendar';
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from '@/components/ui/command';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Modal } from '@/components/ui/modal';
import { MultiSelect } from '@/components/ui/multi-select';
import { OptionCard } from '@/components/ui/option-card';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { Spinner } from '@/components/ui/spinner';
import { Textarea } from '@/components/ui/textarea';
import {
  Toast,
  ToastActions,
  ToastContent,
  ToastFooter,
  ToastHeader,
  ToastItem,
  ToastMessage,
  ToastStatus,
  ToastTitle,
} from '@/components/ui/toast';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';
import { Switch } from '@/components/ui/switch';
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { TimePicker } from '@/components/ui/time-picker';
import { useDarkTheme } from '../hooks';

/**
 * Dev-only style guide, served at /design. It renders every component in
 * src/components/ui with the variants DESIGN.md documents as the defaults,
 * so the page doubles as a visual test of the theme tokens in both modes.
 * Nothing here is translated: the route is not registered in production.
 */

const SECTIONS = [
  ['tokens', 'Colour tokens'],
  ['typography', 'Typography'],
  ['buttons', 'Buttons'],
  ['badges', 'Badges & toasts'],
  ['cards', 'Cards'],
  ['forms', 'Forms'],
  ['dropzone', 'Dropzone'],
  ['feedback', 'Feedback & loading'],
  ['avatars', 'Avatars'],
  ['navigation', 'Navigation'],
  ['tables', 'Tables'],
  ['overlays', 'Overlays'],
  ['pickers', 'Pickers'],
] as const;

const SURFACE_TOKENS = [
  { name: 'background', bg: 'bg-background', fg: 'text-foreground' },
  { name: 'card', bg: 'bg-card', fg: 'text-card-foreground' },
  { name: 'popover', bg: 'bg-popover', fg: 'text-popover-foreground' },
  { name: 'muted', bg: 'bg-muted', fg: 'text-muted-foreground' },
  { name: 'accent', bg: 'bg-accent', fg: 'text-accent-foreground' },
  { name: 'sidebar', bg: 'bg-sidebar', fg: 'text-sidebar-foreground' },
  { name: 'answer-bubble', bg: 'bg-answer-bubble', fg: 'text-foreground' },
] as const;

const BRAND_TOKENS = [
  { name: 'primary', bg: 'bg-primary', fg: 'text-primary-foreground' },
  { name: 'secondary', bg: 'bg-secondary', fg: 'text-secondary-foreground' },
  {
    name: 'destructive',
    bg: 'bg-destructive',
    fg: 'text-destructive-foreground',
  },
  { name: 'success', bg: 'bg-success', fg: 'text-success-foreground' },
  { name: 'warning', bg: 'bg-warning', fg: 'text-warning-foreground' },
  { name: 'info', bg: 'bg-info', fg: 'text-info-foreground' },
] as const;

const LINE_TOKENS = [
  { name: 'border', cls: 'border-border' },
  { name: 'input', cls: 'border-input' },
  { name: 'ring', cls: 'border-ring' },
] as const;

const CHART_TOKENS = [
  'bg-chart-1',
  'bg-chart-2',
  'bg-chart-3',
  'bg-chart-4',
  'bg-chart-5',
] as const;

const BUTTON_VARIANTS = [
  'default',
  'secondary',
  'outline',
  'outline-primary',
  'ghost',
  'ghost-muted',
  'ghost-destructive',
  'link',
  'destructive',
  'destructive-outline',
] as const;

const BUTTON_SIZES = ['xs', 'sm', 'default', 'lg'] as const;
const ICON_SIZES = ['icon-xs', 'icon-sm', 'icon', 'icon-lg'] as const;

const BADGE_VARIANTS = [
  'default',
  'neutral',
  'success',
  'warning',
  'destructive',
  'info',
  'outline',
] as const;

const AVATAR_SIZES = ['sm', 'default', 'lg', 'xl'] as const;

const MULTI_OPTIONS = [
  { value: 'pdf', label: 'PDF' },
  { value: 'docx', label: 'Word' },
  { value: 'md', label: 'Markdown' },
  { value: 'html', label: 'HTML' },
  { value: 'csv', label: 'CSV' },
];

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

const TABLE_ROWS = [
  { name: 'Contracts & Policy Assistant', status: 'success', runs: 128 },
  { name: 'Customer Renewal Desk', status: 'info', runs: 42 },
  { name: 'Vendor Due Diligence', status: 'warning', runs: 9 },
  { name: 'Legacy importer', status: 'destructive', runs: 0 },
] as const;

/** Reads a CSS custom property after the theme class has been applied. */
function useCssVar(name: string, isDark: boolean): string {
  const [value, setValue] = useState('');
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      setValue(
        getComputedStyle(document.documentElement)
          .getPropertyValue(name)
          .trim(),
      );
    });
    return () => cancelAnimationFrame(frame);
  }, [name, isDark]);
  return value;
}

function Section({
  id,
  title,
  intro,
  children,
}: {
  id: string;
  title: string;
  intro: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-24">
      <h2 className="text-foreground text-xl font-semibold">{title}</h2>
      <p className="text-muted-foreground mt-1 max-w-2xl text-sm">{intro}</p>
      <div className="mt-6 flex flex-col gap-8">{children}</div>
    </section>
  );
}

function Example({
  title,
  code,
  children,
}: {
  title: string;
  code?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-foreground text-sm font-medium">{title}</h3>
        {code ? (
          <code className="text-muted-foreground font-mono text-xs">
            {code}
          </code>
        ) : null}
      </div>
      <div className="border-border bg-card rounded-xl border p-6">
        {children}
      </div>
    </div>
  );
}

function Swatch({
  name,
  bg,
  fg,
  isDark,
}: {
  name: string;
  bg: string;
  fg: string;
  isDark: boolean;
}) {
  const value = useCssVar(`--${name}`, isDark);
  return (
    <div className="border-border flex flex-col overflow-hidden rounded-lg border">
      <div className={`${bg} ${fg} flex h-16 items-end px-3 pb-2 text-xs`}>
        Aa
      </div>
      <div className="bg-card px-3 py-2">
        <div className="text-foreground text-xs font-medium">{name}</div>
        <div className="text-muted-foreground font-mono text-xs">{value}</div>
      </div>
    </div>
  );
}

export default function DesignSystem() {
  const [isDark, toggleTheme] = useDarkTheme();
  const scrollRef = useRef<HTMLDivElement>(null);
  const jumpTo = (id: string) => (event: React.MouseEvent) => {
    event.preventDefault();
    const container = scrollRef.current;
    const target = document.getElementById(id);
    if (!container || !target) return;
    // Sections are offset from the scroll container; leave room for the
    // sticky header.
    container.scrollTo({ top: target.offsetTop - 88, behavior: 'smooth' });
    window.history.replaceState(null, '', `#${id}`);
  };
  const [switchOn, setSwitchOn] = useState(true);
  const [formats, setFormats] = useState<string[]>(['pdf', 'md']);
  const [time, setTime] = useState('09:30');
  const [date, setDate] = useState<Date | undefined>(new Date());
  const [modalOpen, setModalOpen] = useState(false);
  const [showArchived, setShowArchived] = useState(true);
  const [dropped, setDropped] = useState<string[]>([]);
  const [agentType, setAgentType] = useState<'classic' | 'workflow'>('classic');
  const [toolOn, setToolOn] = useState(false);
  const [sectionOpen, setSectionOpen] = useState(false);
  const [sourceType, setSourceType] = useState<string>('Upload file');

  return (
    <div
      ref={scrollRef}
      className="bg-background text-foreground relative h-full overflow-y-auto"
    >
      <header className="border-border bg-background/95 sticky top-0 z-20 border-b backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-6 py-3">
          <div className="mr-auto">
            <h1 className="text-base font-semibold">DocsGPT design system</h1>
            <p className="text-muted-foreground text-xs">
              Defaults from frontend/DESIGN.md, rendered with the real
              components. Dev route only.
            </p>
          </div>
          <nav className="hidden flex-wrap gap-1 lg:flex">
            {SECTIONS.map(([id, label]) => (
              <Button key={id} asChild variant="ghost-muted" size="xs">
                <a href={`#${id}`} onClick={jumpTo(id)}>
                  {label}
                </a>
              </Button>
            ))}
          </nav>
          <Button
            variant="outline"
            size="sm"
            shape="pill"
            onClick={toggleTheme}
            aria-label="Toggle theme"
          >
            {isDark ? <Sun /> : <Moon />}
            {isDark ? 'Light' : 'Dark'}
          </Button>
        </div>
      </header>

      <main className="mx-auto flex max-w-6xl flex-col gap-16 px-6 py-10">
        <Section
          id="tokens"
          title="Colour tokens"
          intro="Every colour in the UI resolves to one of these variables from src/index.css. The value shown is the one currently applied, so toggle the theme to compare."
        >
          <Example title="Surfaces" code="bg-card text-card-foreground">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
              {SURFACE_TOKENS.map((t) => (
                <Swatch key={t.name} {...t} isDark={isDark} />
              ))}
            </div>
          </Example>
          <Example
            title="Brand and status"
            code="bg-success text-success-foreground"
          >
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {BRAND_TOKENS.map((t) => (
                <Swatch key={t.name} {...t} isDark={isDark} />
              ))}
            </div>
          </Example>
          <Example title="Lines and charts" code="border-border · bg-chart-1">
            <div className="flex flex-wrap items-center gap-6">
              {LINE_TOKENS.map((t) => (
                <div key={t.name} className="flex items-center gap-2">
                  <div className={`${t.cls} size-10 rounded-md border-2`} />
                  <span className="text-muted-foreground text-xs">
                    {t.name}
                  </span>
                </div>
              ))}
              <div className="flex items-center gap-1">
                {CHART_TOKENS.map((cls) => (
                  <div key={cls} className={`${cls} h-10 w-6 rounded-sm`} />
                ))}
                <span className="text-muted-foreground ml-2 text-xs">
                  chart-1 to chart-5: primary, info, success, warning,
                  destructive
                </span>
              </div>
            </div>
          </Example>
        </Section>

        <Section
          id="typography"
          title="Typography"
          intro="Two text tones cover the app: foreground for content and muted-foreground for everything secondary. Lighter tiers use an opacity modifier, not a lighter grey."
        >
          <Example
            title="Tones"
            code="text-foreground · text-muted-foreground · text-muted-foreground/70"
          >
            <div className="flex flex-col gap-2 text-sm">
              <p className="text-foreground">
                Foreground: titles, body copy, values in tables.
              </p>
              <p className="text-muted-foreground">
                Muted foreground: descriptions, labels, timestamps, icons.
              </p>
              <p className="text-muted-foreground/70">
                Muted at 70%: placeholders and de-emphasised metadata.
              </p>
              <p className="text-primary">
                Primary: links and the selected state.
              </p>
              <p className="text-destructive">Destructive: errors.</p>
            </div>
          </Example>
          <Example
            title="Scale"
            code="text-xs · text-sm · text-base · text-lg · text-xl · font-mono"
          >
            <div className="flex flex-col gap-2">
              <p className="text-xs">Extra small, 12px, badges and hints</p>
              <p className="text-sm">Small, 14px, the default UI size</p>
              <p className="text-base">
                Base, 16px, inputs on mobile and prose
              </p>
              <p className="text-lg font-semibold">
                Large, 18px, dialog titles
              </p>
              <p className="text-xl font-semibold">
                Extra large, 20px, page titles
              </p>
              <p className="font-mono text-sm">Mono: ids, code, token values</p>
            </div>
          </Example>
        </Section>

        <Section
          id="buttons"
          title="Buttons"
          intro="Pick a variant for meaning, a size for density and a shape for the surface it sits on. className is for placement only."
        >
          <Example
            title="Variants × sizes"
            code='<Button variant="…" size="…">'
          >
            <div className="overflow-x-auto">
              <div className="grid min-w-2xl grid-cols-[8rem_repeat(4,auto)] items-center gap-x-6 gap-y-3">
                <span />
                {BUTTON_SIZES.map((size) => (
                  <span
                    key={size}
                    className="text-muted-foreground font-mono text-xs"
                  >
                    {size}
                  </span>
                ))}
                {BUTTON_VARIANTS.map((variant) => (
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
            title="Combobox trigger"
            code='<Button variant="combobox" role="combobox" data-placeholder={value ? undefined : ""}>'
          >
            <div className="flex max-w-md flex-col gap-3">
              <Button
                variant="combobox"
                role="combobox"
                aria-expanded={false}
                data-placeholder=""
                className="w-full justify-between"
              >
                <span className="truncate">Select a timezone…</span>
                <ChevronsUpDown className="size-4 shrink-0 opacity-50" />
              </Button>
              <Button
                variant="combobox"
                role="combobox"
                aria-expanded={false}
                className="w-full justify-between"
              >
                <span className="flex min-w-0 flex-1 items-center justify-between gap-3">
                  <span className="truncate">Europe/Berlin</span>
                  <span className="text-muted-foreground shrink-0 text-xs">
                    UTC+02:00
                  </span>
                </span>
                <ChevronsUpDown className="size-4 shrink-0 opacity-50" />
              </Button>
            </div>
          </Example>
          <Example
            title="Form row (field height)"
            code='<Input shape="pill"> · <SelectTrigger size="lg" shape="pill"> · <Button variant="combobox" size="field" shape="pill">'
          >
            <div className="flex max-w-md flex-col gap-3">
              <Input shape="pill" placeholder="Agent name" />
              <div className="flex gap-2">
                <Select defaultValue="default">
                  <SelectTrigger size="lg" shape="pill" className="flex-1">
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
            title="Link inside running text"
            code='<Button variant="link" size="inline">'
          >
            <p className="text-foreground max-w-md text-base">
              The quarterly review for Halvorsen Logistics is ready. Open{' '}
              <Button variant="link" size="inline">
                QBR report.html
              </Button>{' '}
              to see lane costs and the renewal summary.
            </p>
          </Example>
          <Example
            title="Underline tabs"
            code='<Button variant="tab" data-active={active}>  ·  size="inline" for padding-free tabs'
          >
            <div className="flex flex-col gap-6">
              <div className="border-border flex border-b">
                <Button variant="tab" data-active>
                  My Files
                </Button>
                <Button variant="tab">Shared with Me</Button>
              </div>
              <div className="border-border flex items-center gap-6 border-b">
                <Button
                  variant="tab"
                  size="inline"
                  data-active
                  className="-mb-px"
                >
                  Overview
                </Button>
                <Button variant="tab" size="inline" className="-mb-px">
                  Logs
                </Button>
                <Button variant="tab" size="inline" className="-mb-px">
                  Schedules
                </Button>
              </div>
            </div>
          </Example>
          <Example
            title="Section panel toggle"
            code='<div className="has-[[data-variant=section-toggle]:focus-visible]:ring-3 …"><Button variant="section-toggle" size="sm" aria-expanded>'
          >
            <div className="bg-muted max-w-md rounded-2xl p-4">
              <div className="bg-card has-[[data-variant=section-toggle]:focus-visible]:ring-ring/50 rounded-2xl px-6 py-3 has-[[data-variant=section-toggle]:focus-visible]:ring-3 has-[[data-variant=section-toggle]:focus-visible]:ring-inset">
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="section-toggle"
                    size="sm"
                    aria-expanded={sectionOpen}
                    onClick={() => setSectionOpen(!sectionOpen)}
                    className="-ml-3 w-fit justify-start"
                  >
                    <ChevronRight
                      aria-hidden="true"
                      className={sectionOpen ? 'rotate-90' : undefined}
                    />
                    <span className="text-lg font-semibold">Guardrails</span>
                  </Button>
                  <Badge variant="success">3 active</Badge>
                  <Badge variant="destructive">1 needs setup</Badge>
                </div>
                {sectionOpen && (
                  <p className="text-muted-foreground mt-2 text-sm">
                    Run the selected checks on this agent&apos;s runs.
                  </p>
                )}
              </div>
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
                  <Button
                    variant="ghost-muted"
                    size="icon-sm"
                    shape="pill"
                    aria-label="Copy"
                  >
                    <Copy />
                  </Button>
                  <Button
                    variant="secondary"
                    size="icon-sm"
                    shape="pill"
                    aria-label="Copied"
                  >
                    <Check />
                  </Button>
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
          <Example title="Icon buttons" code='size="icon-xs" … "icon-lg"'>
            <div className="flex flex-wrap items-center gap-6">
              {ICON_SIZES.map((size) => (
                <div key={size} className="flex flex-col items-center gap-2">
                  <div className="flex items-center gap-2">
                    <Button size={size} variant="default" aria-label="Add">
                      <Plus />
                    </Button>
                    <Button size={size} variant="outline" aria-label="Edit">
                      <Pencil />
                    </Button>
                    <Button size={size} variant="ghost-muted" aria-label="More">
                      <MoreHorizontal />
                    </Button>
                    <Button
                      size={size}
                      variant="ghost-destructive"
                      shape="pill"
                      aria-label="Delete"
                    >
                      <Trash2 />
                    </Button>
                  </div>
                  <span className="text-muted-foreground font-mono text-xs">
                    {size}
                  </span>
                </div>
              ))}
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

        <Section
          id="badges"
          title="Badges, toasts & notices"
          intro="Status meaning comes from the four status tokens. Pills are Badge. Messages to the user are toasts in the bottom-right corner. Alert is only for an inline notice inside a form or modal, never for feedback on an action."
        >
          <Example title="Badge variants" code='<Badge variant="success">'>
            <div className="flex flex-wrap items-center gap-2">
              {BADGE_VARIANTS.map((variant) => (
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
            code="<ToastViewport> (one, in App.tsx) > <Toast><ToastHeader variant><ToastTitle wrap?> · <ToastItem icon? label meta><ToastStatus status/> · <ToastMessage variant size>"
          >
            <div className="bg-muted/40 flex flex-wrap items-start gap-4 rounded-xl p-6">
              <Toast>
                <ToastHeader variant="destructive">
                  <ToastTitle>Upload failed</ToastTitle>
                  <ToastActions>
                    <Button
                      size="icon-sm"
                      variant="ghost-muted"
                      aria-label="Collapse"
                    >
                      <ChevronDown />
                    </Button>
                    <Button
                      size="icon-sm"
                      variant="ghost-muted"
                      aria-label="Dismiss"
                    >
                      <X />
                    </Button>
                  </ToastActions>
                </ToastHeader>
                <ToastContent>
                  <ToastItem label="🦖1.png">
                    <ToastStatus status="destructive" />
                  </ToastItem>
                  <ToastMessage variant="destructive">
                    No text could be extracted from this file. It may be empty,
                    image-only, or in an unsupported format.
                  </ToastMessage>
                </ToastContent>
              </Toast>
              <Toast>
                <ToastHeader>
                  <ToastTitle>Upload completed</ToastTitle>
                  <ToastActions>
                    <Button
                      size="icon-sm"
                      variant="ghost-muted"
                      aria-label="Collapse"
                    >
                      <ChevronDown />
                    </Button>
                    <Button
                      size="icon-sm"
                      variant="ghost-muted"
                      aria-label="Dismiss"
                    >
                      <X />
                    </Button>
                  </ToastActions>
                </ToastHeader>
                <ToastContent scrollable>
                  <ToastItem label="Audit.md" meta="1.8k tokens">
                    <ToastStatus status="success" />
                  </ToastItem>
                  <ToastItem label="Tender checklist.docx" meta="Indexing…">
                    <ToastStatus status="pending" />
                  </ToastItem>
                </ToastContent>
              </Toast>
              <Toast>
                <ToastHeader variant="warning">
                  <ToastTitle>Tool approval needed</ToastTitle>
                  <ToastActions>
                    <Button
                      size="icon-sm"
                      variant="ghost-muted"
                      aria-label="Dismiss"
                    >
                      <X />
                    </Button>
                  </ToastActions>
                </ToastHeader>
                <ToastContent>
                  <ToastItem
                    icon={<ToastStatus status="warning" />}
                    label="Vendor Due Diligence"
                    meta="wants to run web_search"
                  />
                  <ToastFooter>
                    <Button size="sm" variant="outline">
                      Deny
                    </Button>
                    <Button size="sm">Approve</Button>
                  </ToastFooter>
                </ToastContent>
              </Toast>
              <Toast>
                <ToastHeader>
                  <ToastTitle wrap>
                    Zu einem Team hinzugefügt: Meridian Freight Operations
                  </ToastTitle>
                  <ToastActions>
                    <Button
                      size="icon-sm"
                      variant="ghost-muted"
                      aria-label="Dismiss"
                    >
                      <X />
                    </Button>
                  </ToastActions>
                </ToastHeader>
                <ToastContent>
                  <ToastMessage size="sm">
                    You were added to Meridian Freight Operations as member
                  </ToastMessage>
                </ToastContent>
              </Toast>
            </div>
          </Example>
          <Example
            title="Inline notices (forms and modals only)"
            code='<Alert variant="default | success | warning | info | destructive">'
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
            </div>
          </Example>
        </Section>

        <Section
          id="cards"
          title="Cards"
          intro="One card, three surfaces. outline is the bordered default; filled is for tiles on a card-coloured page; subtle is a bordered box on a muted page. Interactive cards are the whole target."
        >
          <Example
            title="Entity cards"
            code='<Card variant="outline | filled"> + CardHeader / CardTitle / CardAction / CardFooter'
          >
            <div className="grid gap-4 md:grid-cols-3">
              <Card variant="filled">
                <CardHeader>
                  <CardTitle>
                    Doc 1 - Tender Guidance and Checklist.docx
                  </CardTitle>
                  <CardAction>
                    <Button
                      size="icon-xs"
                      variant="ghost-muted"
                      aria-label="More"
                    >
                      <MoreHorizontal />
                    </Button>
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
                    <Button
                      size="icon-xs"
                      variant="ghost-muted"
                      aria-label="More"
                    >
                      <MoreHorizontal />
                    </Button>
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
                    <Button
                      size="icon-xs"
                      variant="ghost-muted"
                      aria-label="More"
                    >
                      <MoreHorizontal />
                    </Button>
                  </CardAction>
                </CardHeader>
                <CardContent className="flex flex-col gap-1">
                  <CardTitle>Notepad</CardTitle>
                  <CardDescription>
                    Single note. Supports viewing, overwriting, string
                    replacement.
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
            code='<Card> (outline) · <Card interactive asChild><Link/></Card> · <Card padding="sm">'
          >
            <div className="grid gap-4 md:grid-cols-2">
              <Card interactive asChild>
                <a href="#cards">
                  <CardHeader>
                    <div className="flex items-center gap-3">
                      <Avatar size="lg" shape="square" variant="muted">
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
              <Card>
                <CardHeader>
                  <div className="flex items-start gap-3">
                    <Avatar size="xl" shape="circle" imgClassName="size-full" />
                    <div className="flex flex-col gap-1">
                      <CardTitle>DocsGPT New Contact Responder</CardTitle>
                      <CardDescription className="line-clamp-2">
                        This agent processes notifications about new contact
                        form submissions, extracts the name and email address,
                        then drafts a personalised welcome.
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
        </Section>

        <Section
          id="forms"
          title="Forms"
          intro="Inputs and selects share the 42px default height, the sm and lg densities and the pill shape. Labels float inside the field when passed as a prop."
        >
          <Example
            title="Input sizes"
            code='<Input size="sm" | "default" | "lg">'
          >
            <div className="grid gap-4 md:grid-cols-3">
              <div className="flex flex-col gap-2">
                <Label htmlFor="in-sm">Small</Label>
                <Input id="in-sm" size="sm" placeholder="Filter rows…" />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="in-md">Default</Label>
                <Input id="in-md" placeholder="Agent name" />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="in-lg">Large</Label>
                <Input id="in-lg" size="lg" placeholder="Ask anything…" />
              </div>
            </div>
          </Example>
          <Example
            title="Input shapes and states"
            code='shape="pill" · label · leftIcon · aria-invalid · disabled'
          >
            <div className="grid gap-6 md:grid-cols-2">
              <Input size="lg" shape="pill" placeholder="Search the docs" />
              <Input
                shape="pill"
                leftIcon={<Search className="text-muted-foreground size-4" />}
                label="With icon"
              />
              <Input
                leftIcon={<Search className="text-muted-foreground size-4" />}
                placeholder="Search files (icon, no label)"
              />
              <Input label="Floating label" defaultValue="Renewal desk" />
              <Input label="Required" required />
              <Input label="Invalid" aria-invalid defaultValue="not-an-email" />
              <Input label="Disabled" disabled defaultValue="Read only" />
            </div>
          </Example>
          <Example
            title="Floating label on other surfaces"
            code='<Input label="…" labelSurface="card" | "background" | "muted">'
          >
            <div className="grid gap-4 md:grid-cols-3">
              {(['card', 'background', 'muted'] as const).map((surface) => (
                <div
                  key={surface}
                  className={
                    surface === 'card'
                      ? 'bg-card rounded-lg border p-4'
                      : surface === 'background'
                        ? 'bg-background rounded-lg border p-4'
                        : 'bg-muted rounded-lg border p-4'
                  }
                >
                  <Input
                    label={`On ${surface}`}
                    labelSurface={surface}
                    defaultValue="Renewal desk"
                  />
                </div>
              ))}
            </div>
          </Example>
          <Example
            title="Bare field inside a host"
            code='<Input variant="bare">'
          >
            <div className="bg-sidebar w-64 rounded-lg border py-2">
              <div className="bg-sidebar-accent mx-2 flex h-9 items-center gap-1 rounded-3xl pr-1 pl-3">
                <Input
                  variant="bare"
                  aria-label="Conversation name"
                  defaultValue="Q3 carrier renewals"
                  className="flex-1"
                />
                <Button variant="ghost-muted" size="icon-xs" aria-label="Save">
                  <Check />
                </Button>
                <Button
                  variant="ghost-muted"
                  size="icon-xs"
                  aria-label="Cancel"
                >
                  <X />
                </Button>
              </div>
            </div>
          </Example>
          <Example
            title="Field on a muted panel"
            code='<Input variant="filled"> · <Textarea variant="filled">'
          >
            <div className="bg-muted flex max-w-sm flex-col gap-2 rounded-lg p-4">
              <Input
                variant="filled"
                aria-label="Base URL"
                defaultValue="https://api.meridianfreight.example/v2"
              />
              <Textarea
                variant="filled"
                size="sm"
                rows={3}
                aria-label="Banned terms"
                defaultValue={'competitor name\ninternal codename'}
              />
            </div>
          </Example>
          <Example
            title="Select"
            code='<SelectTrigger size="…" variant="…" shape="…">'
          >
            <div className="flex flex-wrap items-center gap-4">
              <Select defaultValue="finance">
                <SelectTrigger size="sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="finance">Small</SelectItem>
                  <SelectItem value="legal">Legal</SelectItem>
                </SelectContent>
              </Select>
              <Select defaultValue="finance">
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="finance">Default</SelectItem>
                  <SelectItem value="legal">Legal</SelectItem>
                </SelectContent>
              </Select>
              <Select defaultValue="finance">
                <SelectTrigger size="lg">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="finance">Large</SelectItem>
                  <SelectItem value="legal">Legal</SelectItem>
                </SelectContent>
              </Select>
              <Select defaultValue="finance">
                <SelectTrigger size="lg" shape="pill">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="finance">Large pill</SelectItem>
                  <SelectItem value="legal">Legal</SelectItem>
                </SelectContent>
              </Select>
              <Select defaultValue="finance">
                <SelectTrigger variant="ghost">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="finance">Ghost</SelectItem>
                  <SelectItem value="legal">Legal</SelectItem>
                </SelectContent>
              </Select>
              <Select>
                <SelectTrigger>
                  <SelectValue placeholder="Placeholder" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="a">Option A</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </Example>
          <Example
            title="Textarea"
            code='<Textarea size="sm | default | lg" resize="none | vertical | both" variant="default | filled">'
          >
            <div className="grid items-start gap-4 md:grid-cols-3">
              <Textarea size="sm" placeholder="Short note…" />
              <Textarea placeholder="Describe what this agent does…" />
              <Textarea
                size="lg"
                resize="none"
                placeholder="System prompt…"
                defaultValue="You are a helpful assistant for Meridian Freight Group."
              />
            </div>
          </Example>
          <Example
            title="Switch and multi-select"
            code="<Switch> · <MultiSelect>"
          >
            <div className="grid items-start gap-6 md:grid-cols-2">
              <div className="flex flex-col gap-4">
                <div className="flex items-center gap-3">
                  <Switch
                    id="sw-1"
                    checked={switchOn}
                    onCheckedChange={setSwitchOn}
                  />
                  <Label htmlFor="sw-1">
                    Notify on failed runs{' '}
                    <span className="text-muted-foreground">
                      ({switchOn ? 'on' : 'off'})
                    </span>
                  </Label>
                </div>
                <div className="flex items-center gap-3">
                  <Switch id="sw-2" disabled />
                  <Label htmlFor="sw-2">Disabled</Label>
                </div>
              </div>
              <MultiSelect
                options={MULTI_OPTIONS}
                selected={formats}
                onChange={setFormats}
                placeholder="Allowed formats"
              />
            </div>
          </Example>
        </Section>

        <Section
          id="dropzone"
          title="Dropzone"
          intro="Click-or-drag file target used by imports and uploads. Colours follow the drag state; pass accept and limits and describe them in the second line."
        >
          <Example
            title="Default and compact"
            code='<Dropzone accept={…} description="…" size="compact">'
          >
            <div className="grid gap-6 md:grid-cols-2">
              <Dropzone
                onDrop={(files) => setDropped(files.map((f) => f.name))}
                accept={{ 'application/x-yaml': ['.yaml', '.yml'] }}
                title="Click to upload or drag and drop a .yaml file"
                description="Agent definitions exported from DocsGPT"
              />
              <div className="flex flex-col gap-4">
                <Dropzone
                  size="compact"
                  multiple
                  onDrop={(files) => setDropped(files.map((f) => f.name))}
                  title="Attach files"
                  description="PDF, Word, Markdown, up to 25 MB each"
                  icon={<FileText />}
                />
                <Dropzone
                  size="compact"
                  disabled
                  onDrop={() => undefined}
                  title="Uploads paused"
                  description="Indexing in progress"
                />
                <Dropzone
                  size="compact"
                  onDrop={() => undefined}
                  title="With an error"
                  error="Only .yaml or .yml files are supported"
                />
                <p className="text-muted-foreground text-xs">
                  Last drop:{' '}
                  {dropped.length ? dropped.join(', ') : 'nothing yet'}
                </p>
              </div>
            </div>
          </Example>
        </Section>

        <Section
          id="feedback"
          title="Feedback & loading"
          intro="Tooltip replaces title attributes; Spinner and Skeleton replace the hand-drawn loaders; Progress replaces width-percent divs."
        >
          <Example
            title="Tooltip"
            code="<Tooltip><TooltipTrigger asChild>…<TooltipContent>"
          >
            <div className="flex flex-wrap items-center gap-3">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button size="icon" variant="ghost-muted" aria-label="Delete">
                    <Trash2 />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Delete source</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button size="icon" variant="ghost-muted" aria-label="Copy">
                    <Copy />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="bottom">
                  Copy conversation link
                </TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Badge variant="neutral">GraphRAG</Badge>
                </TooltipTrigger>
                <TooltipContent>
                  Indexed as a knowledge graph; answers can follow relations
                  between entities.
                </TooltipContent>
              </Tooltip>
              <span className="text-muted-foreground text-xs">
                hover or focus the controls
              </span>
            </div>
          </Example>
          <Example
            title="Spinner and skeleton"
            code='<Spinner size="sm | default | lg"> · <Skeleton className="h-4 w-40">'
          >
            <div className="grid items-start gap-8 md:grid-cols-2">
              <div className="flex items-center gap-6">
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
                <Progress value={18} variant="destructive" size="lg" />
              </div>
            </div>
          </Example>
        </Section>

        <Section
          id="avatars"
          title="Avatars"
          intro="Image avatars keep their own size. Initials boxes take size, shape and a tone."
        >
          <Example
            title="Sizes, shapes, tones"
            code='<Avatar size="lg" shape="circle" variant="primary">LK</Avatar>'
          >
            <div className="flex flex-wrap items-end gap-8">
              <div className="flex items-end gap-3">
                {AVATAR_SIZES.map((size) => (
                  <Avatar
                    key={size}
                    size={size}
                    shape="circle"
                    variant="primary"
                  >
                    LK
                  </Avatar>
                ))}
              </div>
              <div className="flex items-end gap-3">
                {AVATAR_SIZES.map((size) => (
                  <Avatar key={size} size={size} shape="square" variant="muted">
                    MF
                  </Avatar>
                ))}
              </div>
              <div className="flex items-end gap-3">
                <Avatar size="xl" shape="circle" imgClassName="size-full" />
                <Avatar size="lg" shape="square" imgClassName="size-full" />
                <span className="text-muted-foreground self-center text-xs">
                  image, robot fallback
                </span>
              </div>
            </div>
          </Example>
        </Section>

        <Section
          id="navigation"
          title="Navigation"
          intro="Tabs, accordions and breadcrumbs as shipped."
        >
          <Example title="Tabs" code="<Tabs>">
            <Tabs defaultValue="sources">
              <TabsList>
                <TabsTrigger value="sources">Sources</TabsTrigger>
                <TabsTrigger value="tools">Tools</TabsTrigger>
                <TabsTrigger value="guardrails">Guardrails</TabsTrigger>
              </TabsList>
              <TabsContent value="sources">
                <p className="text-muted-foreground pt-4 text-sm">
                  Connected sources and their indexing status.
                </p>
              </TabsContent>
              <TabsContent value="tools">
                <p className="text-muted-foreground pt-4 text-sm">
                  Tools the agent may call.
                </p>
              </TabsContent>
              <TabsContent value="guardrails">
                <p className="text-muted-foreground pt-4 text-sm">
                  Controls applied before and after each turn.
                </p>
              </TabsContent>
            </Tabs>
          </Example>
          <Example
            title="Accordion and breadcrumb"
            code="<Accordion> · <Breadcrumb>"
          >
            <div className="grid gap-8 md:grid-cols-2">
              <Accordion type="single" collapsible defaultValue="a">
                <AccordionItem value="a">
                  <AccordionTrigger>
                    What does re-embedding do?
                  </AccordionTrigger>
                  <AccordionContent>
                    Recomputes vectors for every chunk with the current model.
                  </AccordionContent>
                </AccordionItem>
                <AccordionItem value="b">
                  <AccordionTrigger>Can I pause a schedule?</AccordionTrigger>
                  <AccordionContent>
                    Yes, paused schedules keep their history.
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
              <Breadcrumb>
                <BreadcrumbList>
                  <BreadcrumbItem>
                    <BreadcrumbLink href="#navigation">Agents</BreadcrumbLink>
                  </BreadcrumbItem>
                  <BreadcrumbSeparator />
                  <BreadcrumbItem>
                    <BreadcrumbLink href="#navigation">
                      Renewal desk
                    </BreadcrumbLink>
                  </BreadcrumbItem>
                  <BreadcrumbSeparator />
                  <BreadcrumbItem>
                    <BreadcrumbPage>Schedules</BreadcrumbPage>
                  </BreadcrumbItem>
                </BreadcrumbList>
              </Breadcrumb>
              <Breadcrumb>
                <BreadcrumbList>
                  <BreadcrumbItem>
                    <BreadcrumbLink href="#navigation">Agents</BreadcrumbLink>
                  </BreadcrumbItem>
                  <BreadcrumbSeparator />
                  <BreadcrumbItem>
                    <BreadcrumbPage
                      title="Quarterly renewal desk for key logistics accounts"
                      className="max-w-[16ch]"
                    >
                      Quarterly renewal desk for key logistics accounts
                    </BreadcrumbPage>
                  </BreadcrumbItem>
                </BreadcrumbList>
              </Breadcrumb>
            </div>
          </Example>
        </Section>

        <Section
          id="tables"
          title="Tables"
          intro="Cells accept alignment and typography classes plus text-muted-foreground; everything else is layout."
        >
          <Example
            title="Table with status badges"
            code='<TableCell align="right" className="tabular-nums">'
          >
            <TableContainer>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableHeader>Agent</TableHeader>
                    <TableHeader>Status</TableHeader>
                    <TableHeader align="right">Runs</TableHeader>
                    <TableHeader align="right">Actions</TableHeader>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {TABLE_ROWS.map((row) => (
                    <TableRow key={row.name}>
                      <TableCell className="font-medium">{row.name}</TableCell>
                      <TableCell>
                        <Badge variant={row.status}>{row.status}</Badge>
                      </TableCell>
                      <TableCell align="right" className="tabular-nums">
                        {row.runs}
                      </TableCell>
                      <TableCell align="right">
                        <Button
                          size="icon-sm"
                          variant="ghost-muted"
                          aria-label="Copy"
                        >
                          <Copy />
                        </Button>
                        <Button
                          size="icon-sm"
                          variant="ghost-muted"
                          aria-label="Edit"
                        >
                          <Pencil />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Example>
        </Section>

        <Section
          id="overlays"
          title="Overlays"
          intro="Modal is the only dialog API for app code; the Radix Dialog underneath is private to ui/. Sheet is for side panels. Popovers and menus share the popover surface."
        >
          <Example
            title="Modal and sheet"
            code='<Modal size="md"> · <SheetContent side="right">'
          >
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="outline" onClick={() => setModalOpen(true)}>
                Open modal
              </Button>
              <Modal
                open={modalOpen}
                onOpenChange={setModalOpen}
                title="Move to folder"
                description="Pick where this agent should live."
                footer={
                  <>
                    <Button
                      variant="outline"
                      onClick={() => setModalOpen(false)}
                    >
                      Cancel
                    </Button>
                    <Button onClick={() => setModalOpen(false)}>Move</Button>
                  </>
                }
              >
                <div className="flex flex-col gap-4">
                  <Input label="Folder name" defaultValue="Finance" />
                  <Select defaultValue="team">
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="team">Shared with team</SelectItem>
                      <SelectItem value="me">Only me</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </Modal>
              <Sheet>
                <SheetTrigger asChild>
                  <Button variant="outline">Open sheet</Button>
                </SheetTrigger>
                <SheetContent side="right">
                  <SheetHeader>
                    <SheetTitle>Run details</SheetTitle>
                    <SheetDescription>
                      Started 09:30, finished 09:31, 3 tools called.
                    </SheetDescription>
                  </SheetHeader>
                </SheetContent>
              </Sheet>
            </div>
          </Example>
          <Example
            title="Popover and dropdown menu"
            code="<Popover> · <DropdownMenu>"
          >
            <div className="flex flex-wrap items-center gap-3">
              <Popover>
                <PopoverTrigger asChild>
                  <Button variant="outline">Open popover</Button>
                </PopoverTrigger>
                <PopoverContent>
                  <div className="flex flex-col gap-2">
                    <p className="text-sm font-medium">Retrieval settings</p>
                    <p className="text-muted-foreground text-sm">
                      Chunks per query and the reranker threshold.
                    </p>
                    <Input size="sm" defaultValue="8" label="Chunks" />
                  </div>
                </PopoverContent>
              </Popover>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline">
                    Actions
                    <MoreHorizontal />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  <DropdownMenuLabel>Conversation</DropdownMenuLabel>
                  <DropdownMenuItem>
                    <Pencil />
                    Rename
                  </DropdownMenuItem>
                  <DropdownMenuItem>
                    <Copy />
                    Duplicate
                  </DropdownMenuItem>
                  <DropdownMenuCheckboxItem
                    checked={showArchived}
                    onCheckedChange={(v) => setShowArchived(Boolean(v))}
                  >
                    Show archived
                  </DropdownMenuCheckboxItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem variant="destructive">
                    <Trash2 />
                    Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </Example>
          <Example
            title="Command palette"
            code='<Command variant="palette">, the spacing CommandDialog uses'
          >
            <div className="border-border max-w-md overflow-hidden rounded-lg border">
              <Command variant="palette">
                <CommandInput placeholder="Search agents, sources, settings…" />
                <CommandList>
                  <CommandEmpty>No results.</CommandEmpty>
                  <CommandGroup heading="Agents">
                    <CommandItem>
                      <Settings />
                      Contracts & Policy Assistant
                      <CommandShortcut>⌘1</CommandShortcut>
                    </CommandItem>
                    <CommandItem>
                      <Settings />
                      Customer Renewal Desk
                      <CommandShortcut>⌘2</CommandShortcut>
                    </CommandItem>
                  </CommandGroup>
                  <CommandGroup heading="Actions">
                    <CommandItem>
                      <Plus />
                      New conversation
                    </CommandItem>
                  </CommandGroup>
                </CommandList>
              </Command>
            </div>
          </Example>
          <Example
            title="Chosen item in a picker"
            code="<CommandItem checked={item.id === selectedId}>"
          >
            <div className="border-border max-w-xs overflow-hidden rounded-lg border">
              <Command>
                <CommandList>
                  <CommandItem value="default">default</CommandItem>
                  <CommandItem value="creative" checked>
                    creative
                  </CommandItem>
                  <CommandItem value="strict">strict</CommandItem>
                </CommandList>
              </Command>
            </div>
          </Example>
        </Section>

        <Section
          id="pickers"
          title="Pickers"
          intro="Calendar wraps react-day-picker with the Button ghost variant; TimePicker is two Selects."
        >
          <Example
            title="Calendar and time"
            code='<Calendar mode="single"> · <TimePicker>'
          >
            <div className="flex flex-wrap items-start gap-8">
              <div className="border-border rounded-lg border">
                <Calendar mode="single" selected={date} onSelect={setDate} />
              </div>
              <div className="flex flex-col gap-3">
                <Label>Run at</Label>
                <TimePicker value={time} onChange={setTime} minuteStep={5} />
                <p className="text-muted-foreground flex items-center gap-1 text-xs">
                  <Clock className="size-3" />
                  {date ? date.toLocaleDateString() : 'No date'} at {time}
                </p>
              </div>
            </div>
          </Example>
        </Section>
      </main>
    </div>
  );
}
