import { ChevronDown } from 'lucide-react';
import { type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb';
import { Avatar } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { NavTab } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';

import { buildAgentSection, getVisibleGroups } from '../navigation/sections';
import { selectAnalyticsEnabled } from '../preferences/preferenceSlice';
import { type AccessFields } from '../utils/accessUtils';
import { AGENTS_MANAGE_ROOT } from './paths';

type AgentPageHeaderProps = {
  agentId?: string;
  agentName?: string;
  /** Optional className wrapper for layout tweaks per page. */
  className?: string;
  /**
   * Drop the 1px baseline border under the tabs row. Use when the header is
   * embedded in a container that already provides its own bottom border
   * (e.g. the workflow builder's fixed toolbar) to avoid a double rule.
   */
  inline?: boolean;
  /** The agent's avatar URL; the robot is drawn when it's empty. */
  agentImage?: string;
  /**
   * The current crumb is a button (avatar, name, chevron) that opens the
   * agent's details.
   */
  onNameClick: () => void;
  /** A status Badge placed after the crumbs. */
  status?: ReactNode;
  /**
   * The agent's access fields: each tab shows only when the role allows its
   * page. Omitted (a new workflow, not yet loaded), every tab shows.
   */
  access?: (AccessFields & { status?: string }) | null;
};

/**
 * The workflow builder's toolbar chrome: a Breadcrumb (`Agents > <agent
 * name>`), an optional status Badge, and NavTab links to the agent's pages
 * (hidden until the agent has an id). The builder is full-screen with no
 * sidebar, so it needs its own way between them: the sidebar's tabs
 * (`buildAgentSection`), flat and in its order, with Overview (the builder)
 * always current. The current crumb is the agent's avatar,
 * name and a chevron in a `ghost sm` Button that opens the details, like the
 * phone top bar's chat title. Section pages use
 * `components/AgentPageToolbar` and the sidebar instead.
 */
export default function AgentPageHeader({
  agentId,
  agentName,
  className,
  inline = false,
  agentImage,
  onNameClick,
  status,
  access,
}: AgentPageHeaderProps) {
  const { t } = useTranslation();
  const analyticsEnabled = useSelector(selectAnalyticsEnabled);

  // The builder only edits workflows, so Overview is the builder's path.
  const visibleTabs = agentId
    ? getVisibleGroups(buildAgentSection(agentId, agentName, true, access), {
        features: { analytics: analyticsEnabled === true },
      }).flatMap((group) => group.items)
    : [];
  const displayName = agentName?.trim() || t('agents.pageHeader.fallbackName');

  return (
    <div
      className={cn(
        // The builder only renders from lg, so one row.
        'flex min-w-0 items-center gap-6',
        className,
      )}
    >
      <div className="flex min-w-0 items-center gap-2">
        <Breadcrumb className="min-w-0">
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbLink asChild>
                <Link to={AGENTS_MANAGE_ROOT}>
                  {t('agents.pageHeader.crumbs.agents')}
                </Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-haspopup="dialog"
                onClick={onNameClick}
                // Button is shrink-0; shrink lets a long name truncate.
                className="min-w-0 shrink"
              >
                <Avatar
                  src={agentImage}
                  alt=""
                  shape="circle"
                  className="shrink-0 overflow-hidden"
                  imgClassName="size-5 object-contain"
                />
                {/* The list's muted colour would reach the name; the current
                  crumb is foreground, like BreadcrumbPage, with its 32ch cap. */}
                <span
                  className="text-foreground max-w-[32ch] truncate"
                  title={displayName}
                >
                  {displayName}
                </span>
                <ChevronDown className="text-muted-foreground" aria-hidden />
              </Button>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
        {status}
      </div>

      {agentId && (
        <nav
          aria-label={t('agents.pageHeader.subnavAriaLabel')}
          className={cn(
            'flex items-center',
            // 1px baseline rule under the whole row; the active tab's 2px
            // primary underline sits on top of it.
            !inline && 'border-border border-b',
          )}
        >
          {visibleTabs.map((tab) => (
            // -mb-px lays the tab's 2px underline over the nav's 1px baseline.
            <NavTab
              key={tab.key}
              current={tab.key === 'overview'}
              className="-mb-px"
            >
              {tab.key === 'overview' ? (
                <span>{t(tab.labelKey)}</span>
              ) : (
                <Link to={tab.path}>{t(tab.labelKey)}</Link>
              )}
            </NavTab>
          ))}
        </nav>
      )}
    </div>
  );
}
