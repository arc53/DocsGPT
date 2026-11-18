import { useTranslation } from 'react-i18next';

import FolderTile from '../components/folders/FolderTile';
import { searchParentName } from '../components/folders/folderTree';
import type { Folder, ItemKind } from '../components/folders/types';
import { EmptyState } from '../components/ui/empty-state';
import { SectionHeader } from '../components/ui/section-header';
import type { FolderPage } from './useFolderPage';

const GRID =
  'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4';

type FolderSectionProps = {
  kind: ItemKind;
  page: FolderPage;
  /** The folders this level shows (`listedFolders`). */
  folders: Folder[];
  /** The page's search: a folder it found deeper says where it sits. */
  query: string;
  /** The section's heading ("Folders"). */
  title: string;
};

/**
 * The Folders section of a Tools or Prompts level: a heading with the count
 * and a grid of folder tiles, each with its ⋯ and the other kinds it holds
 * as links. A tree that failed to load shows an error with Retry instead;
 * no folders, nothing.
 */
export default function FolderSection({
  kind,
  page,
  folders,
  query,
  title,
}: FolderSectionProps) {
  const { t } = useTranslation();
  if (page.list.failed && !page.list.loaded)
    return (
      <EmptyState
        size="sm"
        illustration="none"
        tone="destructive"
        title={t('folders.errors.loadFailed')}
        onRetry={page.reload}
      />
    );
  if (folders.length === 0) return null;
  return (
    <section className="flex flex-col gap-3">
      <SectionHeader as="h2" size="sm" title={title} count={folders.length} />
      <div className={GRID}>
        {folders.map((folder) => (
          <FolderTile
            key={folder.id}
            folder={folder}
            kind={kind}
            onOpen={(opened) => page.openFolder(opened.id)}
            menuOptions={page.folderMenu.menuOptions(folder)}
            parentName={
              query.trim()
                ? searchParentName(page.tree, folder, page.folderId)
                : undefined
            }
          />
        ))}
      </div>
    </section>
  );
}
