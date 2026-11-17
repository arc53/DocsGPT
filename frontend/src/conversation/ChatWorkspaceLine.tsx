import { Users } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { MetaItem, MetaLine } from '../components/ui/meta-line';
import { selectCurrentWorkspace } from '../workspace/workspaceSlice';

type ChatWorkspaceLineProps = {
  /** A notice added at the end of the line. */
  notice?: ReactNode;
};

/**
 * The line under the chat composer in a team: "Operations · Only you can see
 * this chat". A chat belongs to the workspace it was started in, but stays
 * its starter's own. When the instance lets a team's admins export its chats,
 * the line names only the team, so nobody reads "only you" about a chat others
 * can export. Nothing in Personal, where every chat is.
 */
export default function ChatWorkspaceLine({ notice }: ChatWorkspaceLineProps) {
  const { t } = useTranslation();
  const workspace = useSelector(selectCurrentWorkspace);
  if (workspace.kind !== 'team') return null;
  return (
    <div
      data-testid="chat-workspace-line"
      className="text-muted-foreground mt-2 px-2 text-xs"
    >
      <MetaLine>
        {workspace.name ? (
          <MetaItem icon={<Users />} title={workspace.name}>
            {workspace.name}
          </MetaItem>
        ) : null}
        {workspace.chat_export ? null : (
          <span>{t('workspace.chat.onlyYou')}</span>
        )}
        {notice}
      </MetaLine>
    </div>
  );
}
