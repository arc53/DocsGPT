import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

import {
  AGENTS_MANAGE_ROOT,
  agentEditPath as agentEditPathProp,
  agentLogsPath,
  agentSchedulesPath,
} from './paths';

export type AgentPageTab = 'overview' | 'logs' | 'schedules';

type AgentPageHeaderProps = {
  agentId?: string;
  agentName?: string;
  /** Route shape for the agent's own root page. Defaults to classic edit URL. */
  agentEditPath?: string;
  currentPage: AgentPageTab;
  /** Optional className wrapper for layout tweaks per page. */
  className?: string;
  /**
   * Drop the 1px baseline border under the tabs row. Use when the header is
   * embedded in a container that already provides its own bottom border
   * (e.g. the workflow builder's fixed toolbar) to avoid a double rule.
   */
  inline?: boolean;
};

/**
 * Shared chrome for the agent sub-pages (Overview/Edit, Logs, Schedules).
 *
 * Top: shadcn Breadcrumb (`Agents > <agent name> > <current page>`).
 * Bottom: underline-style sub-nav linking between the agent's sub-pages.
 */
export default function AgentPageHeader({
  agentId,
  agentName,
  agentEditPath,
  currentPage,
  className,
  inline = false,
}: AgentPageHeaderProps) {
  const { t } = useTranslation();

  const editPath =
    agentEditPath ??
    (agentId ? agentEditPathProp(agentId) : AGENTS_MANAGE_ROOT);
  const tabs = useMemo(
    () => [
      {
        id: 'overview' as const,
        label: t('agents.pageHeader.tabs.overview'),
        href: editPath,
      },
      {
        id: 'logs' as const,
        label: t('agents.pageHeader.tabs.logs'),
        href: agentId ? agentLogsPath(agentId) : '#',
      },
      {
        id: 'schedules' as const,
        label: t('agents.pageHeader.tabs.schedules'),
        href: agentId ? agentSchedulesPath(agentId) : '#',
      },
    ],
    [agentId, editPath, t],
  );

  const currentTabLabel =
    tabs.find((tab) => tab.id === currentPage)?.label ?? '';
  const displayName = agentName?.trim() || t('agents.pageHeader.fallbackName');

  return (
    <div
      className={cn(
        'flex flex-col gap-3 md:flex-row md:items-baseline md:gap-6',
        className,
      )}
    >
      <Breadcrumb className="shrink-0">
        <BreadcrumbList className="flex-nowrap">
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={AGENTS_MANAGE_ROOT}>
                {t('agents.pageHeader.crumbs.agents')}
              </Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            {currentPage === 'overview' ? (
              <BreadcrumbPage title={displayName} className="w-[16ch]">
                {displayName}
              </BreadcrumbPage>
            ) : (
              <BreadcrumbLink asChild>
                <Link to={editPath} className="max-w-[40ch] truncate">
                  {displayName}
                </Link>
              </BreadcrumbLink>
            )}
          </BreadcrumbItem>
          {currentPage !== 'overview' && (
            <>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                <BreadcrumbPage>{currentTabLabel}</BreadcrumbPage>
              </BreadcrumbItem>
            </>
          )}
        </BreadcrumbList>
      </Breadcrumb>

      <nav
        aria-label={t('agents.pageHeader.subnavAriaLabel')}
        className={cn(
          'flex items-center gap-6',
          // 1px baseline rule under the whole row; the active tab's 2px
          // primary underline sits on top of it for the GitHub-style look.
          !inline && 'border-border border-b',
        )}
      >
        {tabs.map((tab) => {
          const isActive = tab.id === currentPage;
          // -mb-px lays the tab's 2px underline over the nav's 1px baseline.
          if (isActive) {
            return (
              <Button
                key={tab.id}
                asChild
                variant="tab"
                size="inline"
                data-active
                className="-mb-px"
              >
                <span aria-current="page">{tab.label}</span>
              </Button>
            );
          }
          return (
            <Button
              key={tab.id}
              asChild
              variant="tab"
              size="inline"
              className="-mb-px"
            >
              <Link to={tab.href}>{tab.label}</Link>
            </Button>
          );
        })}
      </nav>
    </div>
  );
}
