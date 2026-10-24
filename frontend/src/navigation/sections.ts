import {
  Activity,
  BarChart3,
  Blocks,
  CalendarClock,
  CalendarDays,
  ChartNoAxesColumn,
  Database,
  FileClock,
  Gauge,
  Globe,
  History,
  KeyRound,
  LayoutDashboard,
  LayoutGrid,
  LayoutTemplate,
  Lightbulb,
  Plug,
  Radar,
  ScrollText,
  Settings2,
  Shield,
  ShieldCheck,
  SlidersHorizontal,
  SquarePen,
  User,
  UserCog,
  Users,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import {
  ACTIVITY_CALENDAR_PATH,
  ACTIVITY_HISTORY_PATH,
  ACTIVITY_MONITORS_PATH,
  ACTIVITY_NOW_PATH,
  ACTIVITY_ROOT,
  ACTIVITY_SCHEDULES_PATH,
} from '../activity/paths';
import {
  AGENTS_MANAGE_ROOT,
  agentAnalyticsPath,
  agentEditPath,
  agentInsightsPath,
  agentLogsPath,
  agentSchedulesPath,
  agentsFilterPath,
} from '../agents/paths';
import { type AccessFields } from '../utils/accessUtils';
import { canAgent } from '../agents/agentAccess';

/** A single destination in a section's vertical nav. */
export type SectionItem = {
  key: string;
  path: string;
  labelKey: string;
  icon: LucideIcon;
  /** Extra pathnames that also mark this item active (e.g. the section root). */
  aliases?: string[];
  /** Hidden from users without the global admin role. */
  adminOnly?: boolean;
  /** Jumps to a different section rather than navigating within this one. */
  leavesSection?: boolean;
  /** Hidden when the backend reports this feature off (`/api/config`). */
  feature?: 'connectors' | 'analytics';
};

/** Items sharing a heading in the nav. */
export type SectionGroup = {
  key: string;
  labelKey?: string;
  items: SectionItem[];
};

/**
 * A top-level area that takes over the sidebar while the user is inside it.
 * `matches` lists the pathnames the section owns — entering any of them swaps
 * the sidebar from the chat list to this section's nav.
 */
export type Section = {
  key: string;
  rootPath: string;
  /** Fallback title; `title` overrides it when the name comes from data. */
  titleKey: string;
  /** Literal title for a section named after a record, e.g. an agent. */
  title?: string;
  matches: string[];
  /**
   * Where the back button goes. Sections nest — leaving an agent lands on the
   * agent list, not the chat — so back always means "up one level", and the
   * top level is the app.
   */
  parentPath?: string;
  parentLabelKey?: string;
  /**
   * What the page heading says. `'item'` (the default) suits sections whose
   * destinations are separate pages; `'section'` suits ones whose
   * destinations are views of a single page, like the agent list's filters,
   * where the heading would otherwise flip to "All" or "My agents".
   */
  pageTitle?: 'item' | 'section';
  groups: SectionGroup[];
};

export const SETTINGS_SECTION: Section = {
  key: 'settings',
  rootPath: '/settings',
  titleKey: 'settings.label',
  matches: ['/settings', '/teams'],
  groups: [
    {
      key: 'personal',
      labelKey: 'navigation.sections.groups.personal',
      items: [
        {
          key: 'general',
          path: '/settings/general',
          labelKey: 'settings.general.label',
          icon: Settings2,
          aliases: ['/settings'],
        },
        {
          key: 'accessTokens',
          path: '/settings/access-tokens',
          labelKey: 'settings.accessTokens.label',
          icon: KeyRound,
        },
      ],
    },
    {
      key: 'workspace',
      labelKey: 'navigation.sections.groups.workspace',
      items: [
        {
          key: 'sources',
          path: '/settings/knowledge',
          labelKey: 'settings.sources.label',
          icon: Database,
        },
        {
          key: 'connectors',
          path: '/settings/connectors',
          labelKey: 'settings.connectors.label',
          icon: Plug,
          feature: 'connectors',
        },
        {
          key: 'tools',
          path: '/settings/tools',
          labelKey: 'settings.tools.label',
          icon: Wrench,
        },
        {
          key: 'customModels',
          path: '/settings/custom-models',
          labelKey: 'settings.customModels.label',
          icon: Blocks,
        },
        {
          key: 'teams',
          path: '/teams',
          labelKey: 'settings.teams.label',
          icon: Users,
        },
      ],
    },
    {
      key: 'monitoring',
      labelKey: 'navigation.sections.groups.monitoring',
      items: [
        {
          key: 'analytics',
          path: '/settings/analytics',
          labelKey: 'settings.analytics.label',
          icon: ChartNoAxesColumn,
        },
        {
          key: 'insights',
          path: '/settings/insights',
          labelKey: 'settings.insights.label',
          icon: Lightbulb,
          feature: 'analytics',
        },
        {
          key: 'logs',
          path: '/settings/logs',
          labelKey: 'settings.logs.label',
          icon: ScrollText,
        },
      ],
    },
    {
      key: 'administration',
      labelKey: 'navigation.sections.groups.administration',
      items: [
        {
          key: 'admin',
          path: '/admin',
          labelKey: 'admin.label',
          icon: ShieldCheck,
          adminOnly: true,
          leavesSection: true,
        },
      ],
    },
  ],
};

/**
 * What runs and what is planned. Schedules and monitors are the rules that
 * produce the work, grouped as Automations.
 */
export const ACTIVITY_SECTION: Section = {
  key: 'activity',
  rootPath: ACTIVITY_ROOT,
  titleKey: 'activity.label',
  matches: [ACTIVITY_ROOT],
  groups: [
    {
      key: 'activity',
      items: [
        {
          key: 'now',
          path: ACTIVITY_NOW_PATH,
          labelKey: 'activity.now.label',
          icon: Activity,
          aliases: [ACTIVITY_ROOT],
        },
        {
          key: 'calendar',
          path: ACTIVITY_CALENDAR_PATH,
          labelKey: 'activity.calendar.label',
          icon: CalendarDays,
        },
        {
          key: 'history',
          path: ACTIVITY_HISTORY_PATH,
          labelKey: 'activity.history.label',
          icon: History,
        },
      ],
    },
    {
      key: 'automations',
      labelKey: 'navigation.sections.groups.automations',
      items: [
        {
          key: 'schedules',
          path: ACTIVITY_SCHEDULES_PATH,
          labelKey: 'activity.schedules.label',
          icon: CalendarClock,
        },
        {
          key: 'monitors',
          path: ACTIVITY_MONITORS_PATH,
          labelKey: 'monitors.label',
          icon: Radar,
        },
      ],
    },
  ],
};

export const ADMIN_SECTION: Section = {
  key: 'admin',
  rootPath: '/admin',
  titleKey: 'admin.label',
  matches: ['/admin'],
  groups: [
    {
      key: 'admin',
      items: [
        {
          key: 'overview',
          path: '/admin/overview',
          labelKey: 'admin.tabs.overview',
          icon: LayoutDashboard,
          aliases: ['/admin'],
        },
        {
          key: 'users',
          path: '/admin/users',
          labelKey: 'admin.tabs.users',
          icon: Users,
        },
        {
          key: 'admins',
          path: '/admin/roles',
          labelKey: 'admin.tabs.admins',
          icon: UserCog,
        },
        {
          key: 'usage',
          path: '/admin/usage',
          labelKey: 'admin.tabs.usage',
          icon: BarChart3,
        },
        {
          key: 'quotas',
          path: '/admin/quotas',
          labelKey: 'admin.tabs.quotas',
          icon: Gauge,
        },
        {
          key: 'connectors',
          path: '/admin/connectors',
          labelKey: 'admin.tabs.connectors',
          icon: Plug,
          feature: 'connectors',
        },
        {
          key: 'guardrails',
          path: '/admin/guardrails',
          labelKey: 'admin.tabs.guardrails',
          icon: Shield,
        },
        {
          key: 'defaults',
          path: '/admin/defaults',
          labelKey: 'admin.tabs.defaults',
          icon: SlidersHorizontal,
        },
        {
          key: 'audit',
          path: '/admin/audit',
          labelKey: 'admin.tabs.audit',
          icon: FileClock,
        },
      ],
    },
  ],
};

export const AGENTS_SECTION: Section = {
  key: 'agents',
  rootPath: AGENTS_MANAGE_ROOT,
  titleKey: 'agents.title',
  // Only the management prefix. `/agents/:id/c/:conversationId` is a chat and
  // must leave the sidebar on the conversation list.
  matches: [AGENTS_MANAGE_ROOT],
  pageTitle: 'section',
  groups: [
    {
      key: 'agents',
      items: [
        {
          key: 'all',
          path: agentsFilterPath('all'),
          labelKey: 'agents.filters.all',
          icon: LayoutGrid,
        },
        {
          key: 'template',
          path: agentsFilterPath('template'),
          labelKey: 'agents.filters.byDocsGPT',
          icon: LayoutTemplate,
        },
        {
          key: 'user',
          path: agentsFilterPath('user'),
          labelKey: 'agents.filters.byMe',
          icon: User,
        },
        {
          key: 'team',
          path: agentsFilterPath('team'),
          labelKey: 'agents.filters.team',
          icon: Users,
        },
        {
          key: 'shared',
          path: agentsFilterPath('shared'),
          labelKey: 'agents.filters.shared',
          icon: Globe,
        },
      ],
    },
  ],
};

/** The action each agent tab's page needs. */
const TAB_ACTIONS: Record<string, string> = {
  overview: 'view',
  schedules: 'manage_schedules',
  analytics: 'view_logs',
  insights: 'view_logs',
  logs: 'view_logs',
};

/**
 * The nav for a single agent. Built per route rather than declared, because
 * its title is the agent's name and its paths carry the agent's id.
 *
 * Two groups: the agent itself (Overview, Schedules), then Monitoring
 * (Analytics, Insights, Logs), the same three pages Settings has for the
 * whole account. The workflow builder's toolbar and its phone stand-in
 * draw their tabs from this too, so the list lives in one place.
 *
 * `access` is the agent's record once loaded: each tab shows only when the
 * caller's role allows its page (Overview `view`, Schedules
 * `manage_schedules`, the Monitoring pages `view_logs`); a group left
 * empty is dropped. Insights also only shows while the server labels
 * conversations (`feature`, applied by `getVisibleGroups`). Until the
 * record arrives every tab shows, and the route guard sends a caller who
 * may not open a page back to the list.
 *
 * `workflow` is what the path says; only the builder's path says it, so the
 * record's `agent_type` decides on the agent's other pages once loaded.
 */
export function buildAgentSection(
  agentId: string,
  agentName: string | undefined,
  workflow: boolean,
  access?: (AccessFields & { status?: string; agent_type?: string }) | null,
): Section {
  const isWorkflow = workflow || access?.agent_type === 'workflow';
  // The classic edit path still renders a workflow (an old link, or a
  // fallback before the agent loads), so it stays Overview's too.
  const overviewAliases = isWorkflow ? [agentEditPath(agentId, false)] : [];
  const allows = (item: SectionItem) =>
    !access || canAgent(access, TAB_ACTIONS[item.key]);
  const groups: SectionGroup[] = [
    {
      key: 'agent',
      items: [
        {
          key: 'overview',
          path: agentEditPath(agentId, isWorkflow),
          aliases: overviewAliases,
          labelKey: 'agents.pageHeader.tabs.overview',
          icon: SquarePen,
        },
        {
          key: 'schedules',
          path: agentSchedulesPath(agentId),
          labelKey: 'agents.pageHeader.tabs.schedules',
          icon: CalendarClock,
        },
      ],
    },
    {
      key: 'monitoring',
      labelKey: 'navigation.sections.groups.monitoring',
      items: [
        {
          key: 'analytics',
          path: agentAnalyticsPath(agentId),
          labelKey: 'agents.pageHeader.tabs.analytics',
          icon: ChartNoAxesColumn,
        },
        {
          key: 'insights',
          path: agentInsightsPath(agentId),
          labelKey: 'agents.pageHeader.tabs.insights',
          icon: Lightbulb,
          feature: 'analytics',
        },
        {
          key: 'logs',
          path: agentLogsPath(agentId),
          labelKey: 'agents.pageHeader.tabs.logs',
          icon: ScrollText,
        },
      ],
    },
  ];
  const visible = groups
    .map((group) => ({ ...group, items: group.items.filter(allows) }))
    .filter((group) => group.items.length > 0);
  return {
    key: `agent:${agentId}`,
    rootPath: visible[0]?.items[0]?.path ?? agentEditPath(agentId, isWorkflow),
    titleKey: 'agents.pageHeader.fallbackName',
    title: agentName?.trim() || undefined,
    matches: [
      agentEditPath(agentId, isWorkflow),
      ...overviewAliases,
      agentSchedulesPath(agentId),
      agentAnalyticsPath(agentId),
      agentInsightsPath(agentId),
      agentLogsPath(agentId),
    ],
    parentPath: AGENTS_MANAGE_ROOT,
    parentLabelKey: 'navigation.backToAgents',
    groups: visible,
  };
}

export const SECTIONS: Section[] = [
  ACTIVITY_SECTION,
  SETTINGS_SECTION,
  ADMIN_SECTION,
  AGENTS_SECTION,
];

const pathMatches = (pathname: string, path: string): boolean =>
  pathname === path || pathname.startsWith(`${path}/`);

/** The section owning ``pathname``, or null when it is an ordinary app route. */
export function getSectionForPath(pathname: string): Section | null {
  return (
    SECTIONS.find((section) =>
      section.matches.some((match) => pathMatches(pathname, match)),
    ) ?? null
  );
}

/** Flattened items of a section, optionally dropping admin-only entries. */
export function getSectionItems(
  section: Section,
  { isAdmin = true }: { isAdmin?: boolean } = {},
): SectionItem[] {
  return section.groups
    .flatMap((group) => group.items)
    .filter((item) => !item.adminOnly || isAdmin);
}

/** Groups with admin-only entries removed, dropping any group left empty. */
export function getVisibleGroups(
  section: Section,
  {
    isAdmin = true,
    features = {},
  }: {
    isAdmin?: boolean;
    features?: Partial<Record<NonNullable<SectionItem['feature']>, boolean>>;
  } = {},
): SectionGroup[] {
  return section.groups
    .map((group) => ({
      ...group,
      items: group.items.filter(
        (item) =>
          (!item.adminOnly || isAdmin) &&
          (!item.feature || features[item.feature] !== false),
      ),
    }))
    .filter((group) => group.items.length > 0);
}

/**
 * The nav item ``pathname`` belongs to. Longest match wins, so a deeper route
 * (``/settings/tools/slack``) beats a shorter alias (``/settings``).
 */
export function getActiveItem(
  section: Section,
  pathname: string,
): SectionItem | null {
  let best: SectionItem | null = null;
  let bestLength = -1;
  for (const item of getSectionItems(section)) {
    for (const candidate of [item.path, ...(item.aliases ?? [])]) {
      if (pathMatches(pathname, candidate) && candidate.length > bestLength) {
        best = item;
        bestLength = candidate.length;
      }
    }
  }
  return best;
}

/**
 * Which level of the sidebar stack a section occupies: the chat list, a
 * section, or a record inside one.
 */
export const depthOf = (section: Section | null): number =>
  section ? (section.parentPath ? 2 : 1) : 0;
