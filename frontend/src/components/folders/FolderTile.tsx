import type { TFunction } from 'i18next';
import { Folder as FolderIcon } from 'lucide-react';
import { Fragment } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import UsedByAgents from '../../settings/UsedByAgents';
import { agentUseCount } from '../../utils/resourceUsage';
import { Button } from '../ui/button';
import { Card, CardFooter, CardTitle } from '../ui/card';
import { ActionMenu, type MenuOption } from '../ui/dropdown-menu';
import { MetaItem, MetaLine } from '../ui/meta-line';
import {
  folderCount,
  folderCountLine,
  folderKindCount,
  folderOtherKinds,
} from './folderCopy';
import { folderPagePath } from './folderTree';
import type { Folder, ItemKind } from './types';

export type FolderTileProps = {
  folder: Folder;
  /** The page's kind: counted first, the others after "also". */
  kind?: ItemKind;
  onOpen: (folder: Folder) => void;
  /** The folder's ⋯: Rename, Move to folder, Delete (`useFolderMenu`). */
  menuOptions?: MenuOption[];
  /**
   * Where the folder sits ("In Carriers"), first on its line: for a search
   * that lists folders from every level. Left out at the folder's own level.
   */
  parentName?: string;
  /**
   * Each other kind after "also" opens the same folder on its page (default
   * on); off, the line is plain text.
   */
  alsoLinks?: boolean;
};

// A placeholder no count can contain, to split "also {{list}}" around the
// links whatever the language's word order.
const LIST_SLOT = '\u0000';

/**
 * The count line with each other kind a link to the same folder on its page:
 * "6 prompts · also [2 agents], [3 tools]". With nothing of the page's kind
 * and no folders inside, the links stand alone.
 */
function AlsoLinks({
  t,
  folder,
  kind,
  others,
}: {
  t: TFunction;
  folder: Folder;
  kind: ItemKind;
  others: { kind: ItemKind; count: number }[];
}) {
  const own = folderCountLine(t, folder, kind, { also: false });
  const hasOwn =
    folderKindCount(folder, kind) > 0 || (folder.folder_count ?? 0) > 0;
  const [before, after = ''] = hasOwn
    ? t('folders.counts.also', {
        list: LIST_SLOT,
        interpolation: { escapeValue: false },
      }).split(LIST_SLOT)
    : ['', ''];
  return (
    <>
      {hasOwn ? `${own} · ` : null}
      <span data-slot="folder-also">
        {before}
        {others.map((entry, index) => (
          <Fragment key={entry.kind}>
            {index > 0 ? t('folders.listSeparator') : null}
            <Button
              asChild
              variant="link"
              size="text"
              tone="current"
              className="relative z-10"
            >
              <Link to={folderPagePath(entry.kind, folder.id)}>
                {folderCount(t, entry.kind, entry.count)}
              </Link>
            </Button>
          </Fragment>
        ))}
        {after}
      </span>
    </>
  );
}

/**
 * A folder in a tile grid (Agents, Knowledge, Tools, Prompts): a compact
 * `filled` tile with the folder icon, the name on one line, the count line
 * ("6 prompts · also 2 agents, 3 tools", "3 sources · 1 folder", "Empty";
 * after "In Carriers" in a search) and, for a source folder agents read, the
 * usage item, then the ⋯. The other kinds link to the same folder on their
 * pages. A stretched button on the name opens the folder (DESIGN "A
 * clickable card that holds a link"); the ⋯, the links and the usage popover
 * sit above it.
 */
export default function FolderTile({
  folder,
  kind: kindProp,
  onOpen,
  menuOptions = [],
  parentName,
  alsoLinks = true,
}: FolderTileProps) {
  const { t } = useTranslation();
  const kind = kindProp ?? 'agent';
  const used = kind === 'source' && agentUseCount(folder.used_by) > 0;
  const others = alsoLinks ? folderOtherKinds(folder, kind) : [];
  const count = (
    <MetaItem>
      {others.length > 0 ? (
        <AlsoLinks t={t} folder={folder} kind={kind} others={others} />
      ) : (
        folderCountLine(t, folder, kind)
      )}
    </MetaItem>
  );
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
          {parentName ? (
            <MetaItem title={parentName}>
              {t('folders.inParent', {
                name: parentName,
                interpolation: { escapeValue: false },
              })}
            </MetaItem>
          ) : null}
          {count}
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
