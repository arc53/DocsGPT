import { UserRound, Users } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { MetaItem, MetaLine } from '../components/ui/meta-line';
import { cn } from '../lib/utils';
import { selectCurrentWorkspace } from './workspaceSlice';

export type WorkspaceLineKind = 'agents' | 'knowledge' | 'tools' | 'prompts';

type WorkspaceLineProps = {
  /** The page it sits on. */
  kind: WorkspaceLineKind;
  /** A notice added at the end of the line. */
  notice?: ReactNode;
  className?: string;
};

/**
 * The line under a list page's intro that says whose items these are:
 * "Personal · Only you, unless you share an item", or "Operations · Everyone
 * in the team can use what's here · 12 people".
 */
export default function WorkspaceLine({
  kind,
  notice,
  className,
}: WorkspaceLineProps) {
  const { t } = useTranslation();
  const workspace = useSelector(selectCurrentWorkspace);
  const isTeam = workspace.kind === 'team';

  return (
    <div
      data-testid="workspace-line"
      data-kind={kind}
      className={cn('text-muted-foreground mt-2 text-xs', className)}
    >
      <MetaLine>
        {isTeam ? (
          <MetaItem icon={<Users />} title={workspace.name}>
            {workspace.name}
          </MetaItem>
        ) : (
          <MetaItem icon={<UserRound />}>
            {t('workspace.line.personal')}
          </MetaItem>
        )}
        <span>
          {isTeam
            ? t('workspace.line.teamScope')
            : t('workspace.line.personalScope')}
        </span>
        {isTeam && workspace.member_count !== undefined && (
          <span>
            {t('workspace.line.people', { count: workspace.member_count })}
          </span>
        )}
        {notice}
      </MetaLine>
    </div>
  );
}
