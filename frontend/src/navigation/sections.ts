import {
  BarChart3,
  Boxes,
  ChartNoAxesColumn,
  Database,
  FileClock,
  Gauge,
  KeyRound,
  LayoutDashboard,
  ScrollText,
  Settings2,
  ShieldCheck,
  UserCog,
  Users,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import { useLocation } from 'react-router-dom';

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
  titleKey: string;
  matches: string[];
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
          path: '/settings/sources',
          labelKey: 'settings.sources.label',
          icon: Database,
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
          icon: Boxes,
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
          key: 'audit',
          path: '/admin/audit',
          labelKey: 'admin.tabs.audit',
          icon: FileClock,
        },
      ],
    },
  ],
};

export const SECTIONS: Section[] = [SETTINGS_SECTION, ADMIN_SECTION];

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
  { isAdmin = true }: { isAdmin?: boolean } = {},
): SectionGroup[] {
  return section.groups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => !item.adminOnly || isAdmin),
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

/** Route-derived section state — no extra store, so deep links keep working. */
export function useActiveSection(): {
  section: Section | null;
  item: SectionItem | null;
} {
  const { pathname } = useLocation();
  const section = getSectionForPath(pathname);
  return {
    section,
    item: section ? getActiveItem(section, pathname) : null,
  };
}
