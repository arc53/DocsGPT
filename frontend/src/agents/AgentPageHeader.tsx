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
import { cn } from '@/lib/utils';

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
    agentEditPath ?? (agentId ? `/agents/edit/${agentId}` : '/agents');
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
        href: agentId ? `/agents/logs/${agentId}` : '#',
      },
      {
        id: 'schedules' as const,
        label: t('agents.pageHeader.tabs.schedules'),
        href: agentId ? `/agents/schedules/${agentId}` : '#',
      },
    ],
    [agentId, editPath, t],
  );

  const currentTabLabel =
    tabs.find((tab) => tab.id === currentPage)?.label ?? '';
  const displayName = agentName?.trim() || t('agents.pageHeader.fallbackName');

  return (
    <div className={cn('flex flex-row items-baseline gap-6', className)}>
      <Breadcrumb className="shrink-0">
        <BreadcrumbList className="flex-nowrap">
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to="/agents">{t('agents.pageHeader.crumbs.agents')}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            {currentPage === 'overview' ? (
              <BreadcrumbPage className="max-w-[40ch] truncate">
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
          // Always render a 2px bottom border so row height stays constant
          // between active/inactive; only the color changes.
          const baseClasses =
            'whitespace-nowrap border-b-2 pb-1 text-sm font-medium transition-colors';
          if (isActive) {
            return (
              <span
                key={tab.id}
                aria-current="page"
                className={cn(
                  baseClasses,
                  'border-primary text-foreground -mb-px',
                )}
              >
                {tab.label}
              </span>
            );
          }
          return (
            <Link
              key={tab.id}
              to={tab.href}
              className={cn(
                baseClasses,
                'text-muted-foreground hover:text-foreground hover:border-border/60 -mb-px border-transparent',
              )}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
