import { Folder as FolderIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import UsedByAgents from '../../settings/UsedByAgents';
import { agentUseCount } from '../../utils/resourceUsage';
import { Card, CardFooter, CardTitle } from '../ui/card';
import { ActionMenu, type MenuOption } from '../ui/dropdown-menu';
import { MetaItem, MetaLine } from '../ui/meta-line';
import { folderCountLine } from './folderCopy';
import type { Folder, FolderType } from './types';

export type FolderTileProps = {
  folder: Folder;
  type: FolderType;
  onOpen: (folder: Folder) => void;
  /** The folder's ⋯: Rename, Move to folder, Delete (`useFolderMenu`). */
  menuOptions?: MenuOption[];
};

/**
 * A folder in a tile grid (Agents, Knowledge): a compact `filled` tile with
 * the folder icon, the name on one line, the count line ("3 sources · 1
 * folder", "2 agents", "Empty") and, for a source folder agents read, the
 * usage item, then the ⋯. A stretched button on the name opens the folder
 * (DESIGN "A clickable card that holds a link"); the ⋯ and the usage popover
 * sit above it.
 */
export default function FolderTile({
  folder,
  type,
  onOpen,
  menuOptions = [],
}: FolderTileProps) {
  const { t } = useTranslation();
  const used = type === 'source' && agentUseCount(folder.used_by) > 0;
  return (
    <Card
      variant="filled"
      interactive="within"
      className="grid grid-cols-[auto_1fr_auto] items-center gap-x-3 gap-y-0.5"
      data-folder-tile={folder.id}
    >
      <FolderIcon
        className="text-muted-foreground row-span-2 size-6"
        aria-hidden="true"
      />
      <button
        type="button"
        onClick={() => onOpen(folder)}
        className="col-start-2 row-start-1 min-w-0 cursor-pointer text-left outline-none after:absolute after:inset-0 after:rounded-2xl"
      >
        <CardTitle className="truncate">{folder.name}</CardTitle>
      </button>
      <CardFooter className="col-start-2 row-start-2 min-w-0">
        <MetaLine>
          <MetaItem>{folderCountLine(t, folder, type)}</MetaItem>
          {used ? (
            <span className="relative z-10">
              <UsedByAgents usage={folder.used_by} />
            </span>
          ) : null}
        </MetaLine>
      </CardFooter>
      {menuOptions.length > 0 ? (
        <div className="relative z-10 col-start-3 row-span-2 row-start-1">
          <ActionMenu
            options={menuOptions}
            triggerLabel={t('folders.menuLabel', {
              name: folder.name,
              interpolation: { escapeValue: false },
            })}
            align="end"
          />
        </div>
      ) : null}
    </Card>
  );
}
