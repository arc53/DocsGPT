import {
  BarChart3,
  Blocks,
  CalendarClock,
  ChartNoAxesColumn,
  Database,
  FileClock,
  Gauge,
  Globe,
  KeyRound,
  LayoutDashboard,
  LayoutGrid,
  LayoutTemplate,
  Plug,
  Radar,
  ScrollText,
  Settings2,
  ShieldCheck,
  SquarePen,
  User,
  UserCog,
  Users,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import {
  AGENTS_MANAGE_ROOT,
  agentEditPath,
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
  feature?: 'connectors';
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
          key: 'monitors',
          path: '/settings/monitors',
          labelKey: 'monitors.label',
          icon: Radar,
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
      key: 'insights',
      labelKey: 'navigation.sections.groups.insights',
      items: [
        {
          key: 'analytics',
          path: '/settings/analytics',
          labelKey: 'settings.analytics.label',
          icon: ChartNoAxesColumn,
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
  logs: 'view_logs',
  schedules: 'manage_schedules',
};

/**
 * The nav for a single agent. Built per route rather than declared, because
 * its title is the agent's name and its paths carry the agent's id.
 *
 * `access` is the agent's record once loaded: each tab shows only when the
 * caller's role allows its page (Overview `view`, Logs `view_logs`,
 * Schedules `manage_schedules`). Until the record arrives every tab shows,
 * and the route guard sends a caller who may not open a page back to the
 * list.
 */
export function buildAgentSection(
  agentId: string,
  agentName: string | undefined,
  workflow: boolean,
  access?: (AccessFields & { status?: string }) | null,
): Section {
  const allows = (action: string) => !access || canAgent(access, action);
  const items: SectionItem[] = [
    {
      key: 'overview',
      path: agentEditPath(agentId, workflow),
      labelKey: 'agents.pageHeader.tabs.overview',
      icon: SquarePen,
    },
    {
      key: 'logs',
      path: agentLogsPath(agentId),
      labelKey: 'agents.pageHeader.tabs.logs',
      icon: ScrollText,
    },
    {
      key: 'schedules',
      path: agentSchedulesPath(agentId),
      labelKey: 'agents.pageHeader.tabs.schedules',
      icon: CalendarClock,
    },
  ];
  const visible = items.filter((item) => allows(TAB_ACTIONS[item.key]));
  return {
    key: `agent:${agentId}`,
    rootPath: visible[0]?.path ?? agentEditPath(agentId, workflow),
    titleKey: 'agents.pageHeader.fallbackName',
    title: agentName?.trim() || undefined,
    matches: [
      agentEditPath(agentId, workflow),
      agentLogsPath(agentId),
      agentSchedulesPath(agentId),
    ],
    parentPath: AGENTS_MANAGE_ROOT,
    parentLabelKey: 'navigation.backToAgents',
    groups: [{ key: 'agent', items: visible }],
  };
}

export const SECTIONS: Section[] = [
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
