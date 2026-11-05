import { Download } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import {
  artifactKindIcon,
  useArtifactDownload,
  useArtifactMeta,
} from '../components/ArtifactCard';
import ArtifactPanel from '../components/ArtifactPanel';
import { Avatar } from '../components/ui/avatar';
import { Card } from '../components/ui/card';
import { IconButton } from '../components/ui/icon-button';
import { ListRow, ListRows } from '../components/ui/list-row';
import { SectionHeader } from '../components/ui/section-header';
import { PanelBody, PanelHeader } from '../components/ui/side-panel';
import type {
  ArtifactCardItem,
  ArtifactKind,
  OpenArtifactRequest,
} from './artifactCards';

type Group = 'documents' | 'images' | 'data' | 'other';

const GROUP_OF: Record<ArtifactKind, Group> = {
  page: 'documents',
  pdf: 'documents',
  slides: 'documents',
  document: 'documents',
  spreadsheet: 'documents',
  note: 'documents',
  todo: 'documents',
  memory: 'documents',
  image: 'images',
  data: 'data',
  file: 'other',
};

const GROUPS: Group[] = ['documents', 'images', 'data', 'other'];

/**
 * Every artifact of one answer, as side panel content: the level its
 * “N more files” card opens, like the Sources list. The first level lists
 * them grouped by kind; a row opens that artifact as the second level, with
 * a Back arrow to the list. The open artifact is the caller's state.
 *
 * Args:
 *   items: The answer's artifacts, in the order its cards show them.
 *   open: The artifact showing, or null for the list.
 *   onOpenChange: Shows an artifact, or the list again with null.
 *   onBack: Leaves the list (the builder preview's way back to its run).
 *   conversationId: The chat, for the artifact panel's own fetches.
 */
export default function ArtifactsPanel({
  items,
  open,
  onOpenChange,
  onBack,
  conversationId,
}: {
  items: ArtifactCardItem[];
  open: OpenArtifactRequest | null;
  onOpenChange: (open: OpenArtifactRequest | null) => void;
  /** Back from the list itself (the builder preview's run); none in chat. */
  onBack?: () => void;
  conversationId: string | null;
}) {
  const { t } = useTranslation();
  const meta = useArtifactMeta();
  const { download, downloadingId } = useArtifactDownload();

  if (open) {
    return (
      <ArtifactPanel
        key={`${open.id}:${open.version ?? ''}`}
        artifactId={open.id}
        toolName={open.toolName}
        version={open.version}
        conversationId={conversationId}
        onBack={() => onOpenChange(null)}
      />
    );
  }

  return (
    <>
      <PanelHeader
        title={t('conversation.artifacts.listTitle')}
        description={t('conversation.artifacts.fileCount', {
          count: items.length,
        })}
        onBack={onBack}
        backLabel={onBack ? t('agents.workflow.preview.backToRun') : undefined}
      />
      <PanelBody>
        {GROUPS.map((group) => {
          const rows = items.filter((item) => GROUP_OF[item.kind] === group);
          if (rows.length === 0) return null;
          return (
            <section key={group} className="flex flex-col gap-2">
              <SectionHeader
                as="h3"
                size="xs"
                title={t(`conversation.artifacts.group.${group}`)}
                count={rows.length}
              />
              <Card variant="subtle" padding="none" className="overflow-hidden">
                <ListRows>
                  {rows.map((item) => {
                    const Icon = artifactKindIcon(item.kind);
                    return (
                      <ListRow
                        key={item.id}
                        interactive
                        asChild
                        leading={
                          <Avatar size="sm" shape="square" variant="icon">
                            <Icon className="size-4" />
                          </Avatar>
                        }
                        title={
                          <button
                            type="button"
                            data-artifact-row=""
                            title={item.title}
                            className="block max-w-full cursor-pointer truncate text-left outline-none after:absolute after:inset-0"
                            onClick={() =>
                              onOpenChange({
                                id: item.id,
                                toolName: item.toolName,
                                version: item.version,
                              })
                            }
                          >
                            {item.title}
                          </button>
                        }
                        description={meta(item)}
                        trailing={
                          item.downloadable ? (
                            <IconButton
                              label={t('conversation.artifacts.download', {
                                title: item.title,
                              })}
                              icon={Download}
                              variant="ghost-muted"
                              size="icon-sm"
                              shape="pill"
                              loading={downloadingId === item.id}
                              onClick={() => download(item)}
                              className="relative z-10"
                            />
                          ) : null
                        }
                      >
                        {/* The row's box holds the stretched button, so it
                          draws that button's focus ring. */}
                        <div className="has-[[data-artifact-row]:focus-visible]:ring-ring/50 relative has-[[data-artifact-row]:focus-visible]:ring-3 has-[[data-artifact-row]:focus-visible]:ring-inset" />
                      </ListRow>
                    );
                  })}
                </ListRows>
              </Card>
            </section>
          );
        })}
      </PanelBody>
    </>
  );
}
