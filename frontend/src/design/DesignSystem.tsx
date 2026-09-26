import {
  Check,
  CircleAlert,
  TriangleAlert,
  Clock,
  Copy,
  Mail,
  Mic,
  Moon,
  MoreHorizontal,
  Pencil,
  Pin,
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
  Undo2,
  Redo2,
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
  BreadcrumbEllipsis,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  DescriptionItem,
  DescriptionList,
} from '@/components/ui/description-list';
import { Dropzone } from '@/components/ui/dropzone';
import { EmptyState } from '@/components/ui/empty-state';
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
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from '@/components/ui/command';
import {
  ActionMenu,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { FormField } from '@/components/ui/form-field';
import { IconButton } from '@/components/ui/icon-button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ListRow, ListRows } from '@/components/ui/list-row';
import { LoadingState } from '@/components/ui/loading-state';
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from '@/components/ui/message-scroller';
import { Modal, ModalActions } from '@/components/ui/modal';
import { MultiSelect } from '@/components/ui/multi-select';
import { OptionCard } from '@/components/ui/option-card';
import { Pagination } from '@/components/ui/pagination';
import { Progress } from '@/components/ui/progress';
import { SectionHeader } from '@/components/ui/section-header';
import { Separator } from '@/components/ui/separator';
import { SettingRow, SettingRows } from '@/components/ui/setting-row';
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
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
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
  {
    name: 'sidebar-accent',
    bg: 'bg-sidebar-accent',
    fg: 'text-sidebar-accent-foreground',
  },
  {
    name: 'sidebar-primary',
    bg: 'bg-sidebar-primary',
    fg: 'text-sidebar-primary-foreground',
  },
  {
    name: 'sidebar-border',
    bg: 'bg-sidebar-border',
    fg: 'text-sidebar-foreground',
  },
  {
    name: 'sidebar-ring',
    bg: 'bg-sidebar-ring',
    fg: 'text-sidebar-primary-foreground',
  },
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
  'ghost-on-accent',
  'ghost-destructive-on-accent',
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

const AVATAR_SIZES = ['xs', 'sm', 'default', 'lg'] as const;

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
  const [pagerPage, setPagerPage] = useState(2);
  const [formats, setFormats] = useState<string[]>(['pdf', 'md']);
  const [time, setTime] = useState('09:30');
  const [date, setDate] = useState<Date | undefined>(new Date());
  const [modalOpen, setModalOpen] = useState(false);
  const [showArchived, setShowArchived] = useState(true);
  const [dropped, setDropped] = useState<string[]>([]);
  const [agentType, setAgentType] = useState<'classic' | 'workflow'>('classic');
  const [toolOn, setToolOn] = useState(false);
  const [sectionOpen, setSectionOpen] = useState(false);
  const [scopes, setScopes] = useState<string[]>(['agents:read']);
  const [tokenLimit, setTokenLimit] = useState(true);
  const [saving, setSaving] = useState(false);
  const [sourceType, setSourceType] = useState<string>('Upload file');
  const [range, setRange] = useState('30d');
  const [trackRange, setTrackRange] = useState('7d');
  const [days, setDays] = useState<string[]>(['mon', 'wed', 'fri']);
  const [agentFilter, setAgentFilter] = useState('all');
  const [modalDemo, setModalDemo] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [sortBy, setSortBy] = useState('recent');

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
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
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
                Large, 18px, section titles
              </p>
              <p className="text-xl leading-tight font-semibold">
                Extra large, 20px, dialog, sheet and detail-page titles
              </p>
              <p className="font-mono text-xs">Mono 12px: ids, keys, code</p>
            </div>
          </Example>
          <Example
            title="Roles"
            code='<SectionHeader size="default | sm | xs" tone="destructive"> · CardTitle + CardDescription size="xs"'
          >
            <div className="flex max-w-md flex-col gap-6">
              <SectionHeader
                title="Prompts"
                description="System prompts your agents can use."
              />
              <div className="flex flex-col gap-3">
                <SectionHeader as="h3" size="sm" title="Recurring" />
                <SectionHeader as="h3" size="xs" title="Connection" />
                <SectionHeader
                  as="h3"
                  size="xs"
                  tone="destructive"
                  title="Danger zone"
                />
              </div>
              <Card variant="filled">
                <CardTitle>Vendor Due Diligence</CardTitle>
                <CardDescription size="xs">
                  Checks new carriers against sanctions lists and insurance
                  certificates before onboarding.
                </CardDescription>
              </Card>
            </div>
          </Example>
          <Example
            title="Separator"
            code='<Separator /> · <Separator orientation="vertical" />'
          >
            <div className="flex flex-col gap-6">
              <div className="flex max-w-md flex-col gap-3 text-sm">
                <p>Carrier network: 42 carriers across 18 lanes.</p>
                <Separator />
                <p className="text-muted-foreground">
                  Last synced from SharePoint 12 minutes ago.
                </p>
              </div>
              <div className="flex h-8 items-center gap-2">
                <Button variant="ghost" size="sm">
                  Export
                </Button>
                <Separator orientation="vertical" />
                <Button variant="ghost" size="sm">
                  Share
                </Button>
              </div>
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
            title="Link inside running text"
            code='<Button variant="link" size="inline" asChild><a href>'
          >
            <p className="text-foreground max-w-md text-base">
              The quarterly review for Halvorsen Logistics is ready. Open{' '}
              <Button variant="link" size="inline" asChild>
                <a href="#buttons">QBR report.html</a>
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
            title="Segmented control"
            code='<ToggleGroup type="single" value onValueChange={(v) => v && set(v)}> · size="xs" in a bg-muted rounded-full p-1 wrapper · type="multiple"'
          >
            <div className="flex flex-col gap-6">
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
              {/* The track is a plain wrapper: ToggleGroup takes layout only. */}
              <div className="bg-muted max-w-xs rounded-full p-1">
                <ToggleGroup
                  type="single"
                  size="xs"
                  aria-label="Chart range"
                  value={trackRange}
                  onValueChange={(v) => v && setTrackRange(v)}
                  className="w-full"
                >
                  <ToggleGroupItem value="7d" className="flex-1">
                    7d
                  </ToggleGroupItem>
                  <ToggleGroupItem value="30d" className="flex-1">
                    30d
                  </ToggleGroupItem>
                  <ToggleGroupItem value="90d" className="flex-1">
                    90d
                  </ToggleGroupItem>
                </ToggleGroup>
              </div>
              <ToggleGroup
                type="multiple"
                aria-label="Days of the week"
                value={days}
                onValueChange={setDays}
              >
                {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(
                  (day) => (
                    <ToggleGroupItem key={day} value={day.toLowerCase()}>
                      {day}
                    </ToggleGroupItem>
                  ),
                )}
              </ToggleGroup>
              <div className="flex flex-col gap-2">
                <nav
                  aria-label="Agent filters"
                  className="flex flex-wrap gap-1"
                >
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
            code='<IconButton label="Edit" icon={Pencil} size="icon-xs" … "icon-lg">'
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
            code="<ActionMenu options triggerLabel />"
          >
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

        <Section
          id="badges"
          title="Badges, toasts & notices"
          intro="Status meaning comes from the four status tokens. Pills are Badge. A field error is FormField error; a result inside an open modal, or a notice to read before acting, is an Alert; anything else the user did is a toast in the bottom-right corner."
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
            code='<ToastViewport> (one, in App.tsx) > <Toast><ToastHeader variant="default | success | warning | destructive | info"><ToastTitle wrap?> · <ToastItem icon? label meta><ToastStatus status/> · <ToastMessage variant size>'
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
              <Toast>
                <ToastHeader variant="success">
                  <ToastTitle>Sync finished</ToastTitle>
                </ToastHeader>
                <ToastContent>
                  <ToastItem label="SharePoint">
                    <ToastStatus status="success" />
                  </ToastItem>
                  <ToastMessage variant="success">
                    412 documents are up to date.
                  </ToastMessage>
                  <ToastItem label="Google Drive">
                    <ToastStatus status="warning" />
                  </ToastItem>
                  <ToastMessage variant="warning">
                    3 files were skipped: over the 25 MB limit.
                  </ToastMessage>
                  <ToastItem label="Confluence">
                    <ToastStatus status="info" />
                  </ToastItem>
                  <ToastMessage variant="info">
                    Queued behind the nightly re-embed.
                  </ToastMessage>
                </ToastContent>
              </Toast>
              <Toast>
                <ToastHeader variant="info">
                  <ToastTitle>New model available</ToastTitle>
                </ToastHeader>
                <ToastContent>
                  <ToastMessage size="sm">
                    Re-embed your sources to use it for retrieval.
                  </ToastMessage>
                </ToastContent>
              </Toast>
            </div>
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
              <Card>
                <CardHeader>
                  <div className="flex items-start gap-3">
                    <Avatar size="lg" shape="circle" imgClassName="size-full" />
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
            title="Subtle surface and paddings"
            code='<Card variant="subtle"> on bg-muted · tone="destructive" · padding="lg" · padding="none"'
          >
            <div className="bg-muted grid items-start gap-4 rounded-2xl p-4 md:grid-cols-2">
              <Card variant="subtle" padding="lg">
                <CardTitle>Subtle</CardTitle>
                <CardDescription>
                  subtle is a bordered background-coloured box on a muted page;
                  lg pads it 24px.
                </CardDescription>
              </Card>
              <Card tone="destructive" padding="lg">
                <CardTitle>Danger zone</CardTitle>
                <CardDescription>
                  tone=&quot;destructive&quot;: the status soft fill and border,
                  for danger zones and a red stat tile.
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
            code="<ListRows><ListRow leading title description trailing interactive asChild>"
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
                    <span className="bg-muted text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-md">
                      <FileText className="size-4" />
                    </span>
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
            title="Key/value rows"
            code='<DescriptionList layout="columns | justified" size="sm | xs"><DescriptionItem label mono>'
          >
            <div className="grid items-start gap-6 md:grid-cols-2">
              <DescriptionList>
                <DescriptionItem label="Status">
                  <Badge variant="success">Success</Badge>
                </DescriptionItem>
                <DescriptionItem label="Started">
                  24/09/2026, 09:00
                </DescriptionItem>
                <DescriptionItem label="Endpoint" mono>
                  https://api.meridianfreight.example/v2/carriers/renewals
                </DescriptionItem>
              </DescriptionList>
              <DescriptionList layout="justified">
                <DescriptionItem label="Last used">
                  3 minutes ago
                </DescriptionItem>
                <DescriptionItem label="Tokens">1,204</DescriptionItem>
              </DescriptionList>
            </div>
          </Example>
          <Example
            title="Pager"
            code='<Pagination page pageCount onPageChange pageSize? summary? labels="icons | text">'
          >
            <div className="flex flex-col gap-4">
              <Pagination
                page={pagerPage}
                pageCount={5}
                onPageChange={setPagerPage}
                pageSize={10}
                onPageSizeChange={() => undefined}
              />
              <Pagination
                page={pagerPage}
                pageCount={5}
                onPageChange={setPagerPage}
                summary="1,024 users"
              />
            </div>
          </Example>
          <Example
            title="Empty, loading and failed"
            code="<EmptyState size tone illustration> · <LoadingState fill label>"
          >
            <div className="grid items-center gap-6 md:grid-cols-3">
              <EmptyState size="sm" title="No existing Sources" />
              <EmptyState
                tone="destructive"
                size="sm"
                illustration="none"
                title="Failed to load usage."
                action={
                  <Button variant="outline" size="sm">
                    Retry
                  </Button>
                }
              />
              <LoadingState fill="block" label="Converting..." />
            </div>
          </Example>
        </Section>

        <Section
          id="forms"
          title="Forms"
          intro="Inputs and selects share the 38px form-row height (size field), the sm and lg densities and the pill shape. Every form field is labelled by a floating label (FormField, or the Input label shorthand)."
        >
          <Example
            title="Input sizes"
            code='<Input size="sm" | "default" | "field" | "lg">'
          >
            <div className="grid gap-4 md:grid-cols-4">
              <div className="flex flex-col gap-2">
                <Label htmlFor="in-sm">Small</Label>
                <Input id="in-sm" size="sm" placeholder="Filter rows…" />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="in-md">Default</Label>
                <Input id="in-md" placeholder="Agent name" />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="in-field">Field (38px form row)</Label>
                <Input id="in-field" size="field" placeholder="Server URL" />
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
                <IconButton
                  variant="ghost-muted"
                  size="icon-xs"
                  label="Save"
                  icon={Check}
                />
                <IconButton
                  variant="ghost-muted"
                  size="icon-xs"
                  label="Cancel"
                  icon={X}
                />
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
                <SelectTrigger size="field">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="finance">Large</SelectItem>
                  <SelectItem value="legal">Legal</SelectItem>
                </SelectContent>
              </Select>
              <Select defaultValue="finance">
                <SelectTrigger size="field" shape="pill">
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
            title="FormField"
            code="<FormField label required hint error disabled labelSurface float>{field}</FormField>"
          >
            <div className="grid items-start gap-6 md:grid-cols-3">
              <FormField
                label="Server name"
                required
                hint="Shown in the tool list"
              >
                <Input placeholder="My MCP server" />
              </FormField>
              <FormField label="Authentication type">
                <Select defaultValue="none">
                  <SelectTrigger size="field" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">No authentication</SelectItem>
                    <SelectItem value="bearer">Bearer token</SelectItem>
                  </SelectContent>
                </Select>
              </FormField>
              <FormField
                label="Server URL"
                required
                error="Server URL is required"
              >
                <Input placeholder="https://" />
              </FormField>
              <FormField label="Description" hint="Optional">
                <Textarea rows={3} placeholder="What this server is for" />
              </FormField>
              <div className="bg-muted rounded-2xl p-4">
                <FormField label="Policy" labelSurface="muted">
                  <Textarea rows={3} />
                </FormField>
              </div>
              <FormField label="Scopes" float={false}>
                <div className="flex flex-col gap-2 text-sm">
                  <span>Agents: read</span>
                  <span>Sources: read and write</span>
                </div>
              </FormField>
            </div>
          </Example>
          <Example
            title="SettingRow"
            code='<SettingRows><SettingRow label description htmlFor after alignStart as="label | h2 | h3">{control}</SettingRow></SettingRows>'
          >
            <SettingRows className="max-w-xl">
              <SettingRow
                label="Token limiting"
                description="Limit daily total tokens that can be used by this agent"
                htmlFor="ds-token-limiting"
                after={
                  <Input
                    shape="pill"
                    placeholder="Enter token limit"
                    disabled={!tokenLimit}
                  />
                }
              >
                <Switch
                  id="ds-token-limiting"
                  checked={tokenLimit}
                  onCheckedChange={setTokenLimit}
                />
              </SettingRow>
              <SettingRow
                label="Allow prompt override"
                description="Let v1 API callers replace this agent's system prompt"
                htmlFor="ds-prompt-override"
              >
                <Switch id="ds-prompt-override" />
              </SettingRow>
              <SettingRow
                as="h3"
                label="Guardrails"
                description="A heading title keeps the outline; the control names itself"
              >
                <Switch aria-label="Enable guardrails" />
              </SettingRow>
              <SettingRow
                alignStart
                label="Redact personal data"
                description="Mask names, email addresses, phone numbers and account ids in both the question and the answer before they are stored in the run log. Wrapped descriptions top-align the control."
                htmlFor="ds-redact"
              >
                <Switch id="ds-redact" />
              </SettingRow>
            </SettingRows>
          </Example>
          <Example
            title="Checkbox"
            code='<Checkbox size="sm | default" checked onCheckedChange>'
          >
            <div className="flex flex-col gap-3">
              {['agents:read', 'agents:write', 'agents:keys'].map((scope) => (
                <div key={scope} className="flex items-center gap-3">
                  <Checkbox
                    id={`ds-${scope}`}
                    checked={scopes.includes(scope)}
                    onCheckedChange={(checked) =>
                      setScopes((current) =>
                        checked === true
                          ? [...current, scope]
                          : current.filter((s) => s !== scope),
                      )
                    }
                  />
                  <Label htmlFor={`ds-${scope}`} className="font-mono">
                    {scope}
                  </Label>
                </div>
              ))}
              <div className="flex items-center gap-3">
                <Checkbox id="ds-cb-sm" size="sm" defaultChecked />
                <Label htmlFor="ds-cb-sm">Small (table cells)</Label>
              </div>
              <div className="flex items-center gap-3">
                <Checkbox id="ds-cb-disabled" disabled defaultChecked />
                <Label htmlFor="ds-cb-disabled">Disabled</Label>
              </div>
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
                Header and toolbar buttons open below; buttons under text, in
                the composer and in rows open above. Toast close and collapse
                stay a plain Button with aria-label.
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
                <Progress value={18} variant="destructive" size="lg" />
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
                                ? 'bg-answer-bubble ml-auto w-fit max-w-[80%] rounded-2xl px-3 py-2 text-sm'
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

        <Section
          id="avatars"
          title="Avatars"
          intro="Image avatars keep their own size. Initials boxes take size, shape and a tone."
        >
          <Example
            title="Sizes, shapes, tones"
            code='<Avatar size="xs | sm | default | lg" shape="circle" variant="primary">LK</Avatar>'
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
                <Avatar size="lg" shape="circle" imgClassName="size-full" />
                <Avatar
                  size="default"
                  shape="square"
                  imgClassName="size-full"
                />
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
            title="Underline tabs"
            code='<TabsList variant="underline"> · <TabsTrigger variant="underline">'
          >
            <Tabs defaultValue="my_files">
              <TabsList variant="underline">
                <TabsTrigger variant="underline" value="my_files">
                  My Files
                </TabsTrigger>
                <TabsTrigger variant="underline" value="shared">
                  Shared with Me
                </TabsTrigger>
              </TabsList>
              <TabsContent value="my_files">
                <p className="text-muted-foreground pt-4 text-sm">
                  Files in your own drive.
                </p>
              </TabsContent>
              <TabsContent value="shared">
                <p className="text-muted-foreground pt-4 text-sm">
                  Files other people shared with you.
                </p>
              </TabsContent>
            </Tabs>
          </Example>
          <Example
            title="Accordion and breadcrumb"
            code="<Accordion> · <Breadcrumb> · <BreadcrumbEllipsis />"
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
              <Breadcrumb>
                <BreadcrumbList>
                  <BreadcrumbItem>
                    <BreadcrumbLink href="#navigation">Sources</BreadcrumbLink>
                  </BreadcrumbItem>
                  <BreadcrumbSeparator />
                  <BreadcrumbItem>
                    <BreadcrumbEllipsis />
                  </BreadcrumbItem>
                  <BreadcrumbSeparator />
                  <BreadcrumbItem>
                    <BreadcrumbPage>Carrier contracts</BreadcrumbPage>
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
                        <IconButton
                          size="icon-sm"
                          variant="ghost-muted"
                          label="Copy"
                          icon={Copy}
                        />
                        <IconButton
                          size="icon-sm"
                          variant="ghost-muted"
                          label="Edit"
                          icon={Pencil}
                        />
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
          intro="Modal is the only dialog API for app code; the Radix Dialog underneath is private to ui/. Sheet is for side panels and phone bottom sheets. Popovers and menus share the popover surface."
        >
          <Example
            title="Modal and sheet"
            code='<Modal size="md" title description footer={<ModalActions …/>}> · <SheetContent side="right | left | top"> · <SheetContent side="bottom" handle>'
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
                  <ModalActions
                    cancelLabel="Cancel"
                    onCancel={() => setModalOpen(false)}
                    submitLabel="Move"
                    onSubmit={() => setModalOpen(false)}
                  />
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
              <Sheet>
                <SheetTrigger asChild>
                  <Button variant="outline">Left sheet</Button>
                </SheetTrigger>
                <SheetContent side="left">
                  <SheetHeader>
                    <SheetTitle>Folders</SheetTitle>
                    <SheetDescription>
                      side=&quot;left&quot;: a navigation drawer.
                    </SheetDescription>
                  </SheetHeader>
                </SheetContent>
              </Sheet>
              <Sheet>
                <SheetTrigger asChild>
                  <Button variant="outline">Top sheet</Button>
                </SheetTrigger>
                <SheetContent side="top">
                  <SheetHeader>
                    <SheetTitle>Announcement</SheetTitle>
                    <SheetDescription>
                      side=&quot;top&quot;: full width, as tall as its content.
                    </SheetDescription>
                  </SheetHeader>
                </SheetContent>
              </Sheet>
              <Sheet>
                <SheetTrigger asChild>
                  <Button variant="outline">Open bottom sheet</Button>
                </SheetTrigger>
                <SheetContent side="bottom" handle showCloseButton={false}>
                  <SheetHeader>
                    <SheetTitle>Tools</SheetTitle>
                    <SheetDescription>
                      The phone picker shape: card fill, rounded top, grab
                      handle, clear of the home indicator.
                    </SheetDescription>
                  </SheetHeader>
                </SheetContent>
              </Sheet>
            </div>
          </Example>
          <Example
            title="Modal sizes and footers"
            code='size="sm | lg | xl | full" · mobileVariant="sheet" · hideTitle · <ModalActions destructive | pending | footerStart> · no submitLabel = Cancel only'
          >
            <div className="flex flex-wrap items-center gap-3">
              {(
                [
                  ['sm', 'sm, destructive'],
                  ['lg', 'lg, footerStart'],
                  ['xl', 'xl, cancel only'],
                  ['full', 'full, pending'],
                  ['sheet', 'Sheet on phones'],
                  ['hidden', 'hideTitle'],
                ] as const
              ).map(([id, label]) => (
                <Button
                  key={id}
                  variant="outline"
                  size="sm"
                  onClick={() => setModalDemo(id)}
                >
                  {label}
                </Button>
              ))}
              <Modal
                size="sm"
                open={modalDemo === 'sm'}
                onOpenChange={(open) => !open && setModalDemo(null)}
                title="Delete source?"
                description="Carrier contracts and its 1,204 chunks will be removed. Agents using it lose the source."
                footer={
                  <ModalActions
                    cancelLabel="Cancel"
                    onCancel={() => setModalDemo(null)}
                    submitLabel="Delete"
                    destructive
                    onSubmit={() => setModalDemo(null)}
                  />
                }
              >
                <p className="text-muted-foreground text-sm">
                  This can&apos;t be undone.
                </p>
              </Modal>
              <Modal
                size="lg"
                open={modalDemo === 'lg'}
                onOpenChange={(open) => !open && setModalDemo(null)}
                title="Edit MCP server"
                footer={
                  <ModalActions
                    footerStart={
                      <Button variant="outline" size="lg" shape="pill">
                        Test connection
                      </Button>
                    }
                    cancelLabel="Cancel"
                    onCancel={() => setModalDemo(null)}
                    submitLabel="Save"
                    onSubmit={() => setModalDemo(null)}
                  />
                }
              >
                <div className="flex flex-col gap-4">
                  <Input label="Server name" defaultValue="Carrier rates" />
                  <Input
                    label="Server URL"
                    defaultValue="https://mcp.meridianfreight.example"
                  />
                </div>
              </Modal>
              <Modal
                size="xl"
                open={modalDemo === 'xl'}
                onOpenChange={(open) => !open && setModalDemo(null)}
                title="Run details"
                description="Read only: the footer is Cancel alone."
                footer={
                  <ModalActions
                    cancelLabel="Close"
                    onCancel={() => setModalDemo(null)}
                  />
                }
              >
                <p className="text-muted-foreground text-sm">
                  Started 09:30, finished 09:31, 3 tools called.
                </p>
              </Modal>
              <Modal
                size="full"
                open={modalDemo === 'full'}
                onOpenChange={(open) => !open && setModalDemo(null)}
                title="Import agents"
                footer={
                  <ModalActions
                    cancelLabel="Cancel"
                    onCancel={() => setModalDemo(null)}
                    submitLabel="Import"
                    pending
                  />
                }
              >
                <p className="text-muted-foreground text-sm">
                  pending spins and disables the submit; the label stays.
                </p>
              </Modal>
              <Modal
                mobileVariant="sheet"
                open={modalDemo === 'sheet'}
                onOpenChange={(open) => !open && setModalDemo(null)}
                title="Share to team"
                description="A centred modal from sm up; a bottom sheet with a grab handle on phones."
                footer={
                  <ModalActions
                    cancelLabel="Cancel"
                    onCancel={() => setModalDemo(null)}
                    submitLabel="Share"
                    onSubmit={() => setModalDemo(null)}
                  />
                }
              >
                <Input label="Add people" />
              </Modal>
              <Modal
                hideTitle
                open={modalDemo === 'hidden'}
                onOpenChange={(open) => !open && setModalDemo(null)}
                title="Image preview"
              >
                <div className="bg-muted flex h-48 items-center justify-center rounded-lg">
                  <FileText className="text-muted-foreground size-8" />
                </div>
                <p className="text-muted-foreground mt-3 text-xs">
                  The title is still announced to screen readers.
                </p>
              </Modal>
            </div>
          </Example>
          <Example
            title="Popover and dropdown menu"
            code="<Popover> · <DropdownMenu> with Shortcut, Sub, RadioGroup, CheckboxItem"
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
                    <DropdownMenuShortcut>F2</DropdownMenuShortcut>
                  </DropdownMenuItem>
                  <DropdownMenuItem>
                    <Copy />
                    Duplicate
                    <DropdownMenuShortcut>⌘D</DropdownMenuShortcut>
                  </DropdownMenuItem>
                  <DropdownMenuSub>
                    <DropdownMenuSubTrigger>
                      <Book />
                      Move to
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent>
                      <DropdownMenuItem>Finance</DropdownMenuItem>
                      <DropdownMenuItem>Legal</DropdownMenuItem>
                      <DropdownMenuItem>Operations</DropdownMenuItem>
                    </DropdownMenuSubContent>
                  </DropdownMenuSub>
                  <DropdownMenuSeparator />
                  <DropdownMenuLabel>Sort by</DropdownMenuLabel>
                  <DropdownMenuRadioGroup
                    value={sortBy}
                    onValueChange={setSortBy}
                  >
                    <DropdownMenuRadioItem value="recent">
                      Most recent
                    </DropdownMenuRadioItem>
                    <DropdownMenuRadioItem value="name">
                      Name
                    </DropdownMenuRadioItem>
                  </DropdownMenuRadioGroup>
                  <DropdownMenuSeparator />
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
            code='<Command variant="palette">, the spacing CommandDialog uses · <CommandDialog open onOpenChange title description>'
          >
            <div className="flex flex-col items-start gap-4">
              <Button variant="outline" onClick={() => setPaletteOpen(true)}>
                <Search />
                Open CommandDialog
              </Button>
              <CommandDialog
                open={paletteOpen}
                onOpenChange={setPaletteOpen}
                title="Search conversations"
                description="Search your conversations by title"
              >
                <CommandInput placeholder="Search conversations…" />
                <CommandList>
                  <CommandEmpty>No results.</CommandEmpty>
                  <CommandGroup heading="Recent">
                    <CommandItem onSelect={() => setPaletteOpen(false)}>
                      <MessageSquare />
                      Q3 carrier renewals
                    </CommandItem>
                    <CommandItem onSelect={() => setPaletteOpen(false)}>
                      <MessageSquare />
                      Halvorsen lane costs
                    </CommandItem>
                  </CommandGroup>
                </CommandList>
              </CommandDialog>
              <div className="border-border w-full max-w-md overflow-hidden rounded-lg border">
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
                  {date ? date.toLocaleDateString('en-GB') : 'No date'} at{' '}
                  {time}
                </p>
              </div>
            </div>
          </Example>
        </Section>
      </main>
    </div>
  );
}
