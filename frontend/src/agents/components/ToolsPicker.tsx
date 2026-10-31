import {
  type MouseEvent,
  type ReactNode,
  useCallback,
  useMemo,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';

import { MultiSelectPopover } from '../../components/MultiSelectPopover';
import PickerFooter from '../../components/PickerFooter';
import {
  type PickerTool,
  toolPickerItems,
} from '../../components/toolPickerItems';
import { connectionNeedsSignIn } from '../../connectors/connectorsSlice';
import SignInAgainNotice from '../../connectors/SignInAgainNotice';
import type { Connection, ConnectorDefinition } from '../../connectors/types';
import { useDeviceOnline } from '../../hooks/useDeviceOnline';
import type { LeaveTo } from '../../hooks/useLeaveGuard';
import { usePickerKindFilter } from '../../hooks/usePickerKindFilter';
import AddToolModal from '../../modals/AddToolModal';
import type { ActiveState } from '../../models/misc';
import {
  TOOL_KINDS,
  toolKindLabel,
  toolKindOf,
  type ToolKindFilter,
} from '../../settings/toolGroups';

export type ToolsPickerProps<T extends PickerTool> = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The reader's tools. */
  tools: T[];
  /**
   * Which tools this picker offers (`isAgentPickerToolVisible` for an agent,
   * `isWorkflowNodeToolVisible` for a workflow node).
   */
  filter: (tool: T) => boolean;
  /**
   * Tools on the agent or node the reader can't list (the owner's private
   * ones on a shared agent): each gets a row, so it can be taken off.
   */
  attached?: PickerTool[];
  /** The line of an attached row. */
  attachedLine: string;
  /** The ids picked on the agent or node. */
  selectedIds: string[];
  onToggle: (id: string) => void;
  /** The reader's own connections and the connector catalog, for the rows. */
  connections: Connection[];
  catalog: ConnectorDefinition[];
  /** Who added a tool ("Added by Lena"), joined to its row's line. */
  addedBy?: (id: string) => string | null;
  /**
   * Signs a broken connection behind the reader's tools in again; given, a
   * notice above the footer offers it.
   */
  onReconnect?: (connection: Connection, mcpToolId?: string) => void;
  /** The picker's trigger. */
  trigger: ReactNode;
  /**
   * The Go to Tools link's click, after the picker closed: a builder
   * prevents it and asks first while it has unsaved changes.
   */
  onNavigate: (event: MouseEvent<HTMLAnchorElement>) => void;
  /** Reloads the reader's tools (Add tool changed something). */
  onReloadTools: () => void;
  /** The tools Add tool made, to put on (`useAttachAddedTools`). */
  onToolsCreated: (toolIds: string[]) => void;
  /** Add tool's ways out, through the builder's leave guard. */
  onLeaveTo?: LeaveTo;
};

/**
 * The tools picker of the agent builder and a workflow agent node: the
 * reader's tools as this picker offers them, grouped as the Tools page
 * groups them with a kind track, a remote device's status, who added a tool,
 * a remove-only row for each attached tool the reader can't list, a notice
 * for a connection that needs signing in again, and a footer to Tools and to
 * Add tool.
 */
export default function ToolsPicker<T extends PickerTool>({
  open,
  onOpenChange,
  tools,
  filter,
  attached = [],
  attachedLine,
  selectedIds,
  onToggle,
  connections,
  catalog,
  addedBy,
  onReconnect,
  trigger,
  onNavigate,
  onReloadTools,
  onToolsCreated,
  onLeaveTo,
}: ToolsPickerProps<T>) {
  const { t } = useTranslation();
  const [addToolState, setAddToolState] = useState<ActiveState>('INACTIVE');
  const offered = useMemo(() => tools.filter(filter), [tools, filter]);
  // The offered tools, then a row for each attached one not among them.
  const rows = useMemo<PickerTool[]>(() => {
    const seen = new Set(offered.map((tool) => tool.id));
    const extra = attached.filter((tool) => {
      if (!tool?.id || seen.has(tool.id)) return false;
      seen.add(tool.id);
      return true;
    });
    return [...offered, ...extra];
  }, [attached, offered]);
  const listed = useMemo(
    () => new Set(offered.map((tool) => tool.id)),
    [offered],
  );

  const matches = useCallback(
    (kind: ToolKindFilter, tool: PickerTool) =>
      kind === 'all' || toolKindOf(tool, connections, catalog) === kind,
    [connections, catalog],
  );
  // The kind track, back on All each time the picker opens.
  const kinds = usePickerKindFilter(rows, open, {
    kinds: TOOL_KINDS,
    matches,
    labelOf: (kind) => toolKindLabel(t, kind),
    ariaLabel: t('settings.tools.kindFilterLabel'),
  });
  // Remote devices' online state, asked for each time the picker opens.
  const deviceOnline = useDeviceOnline(open, offered);
  const items = useMemo(
    () =>
      toolPickerItems(kinds.items, {
        t,
        connections,
        catalog,
        deviceOnline,
        lineFor: (tool) => (listed.has(tool.id) ? undefined : attachedLine),
        // Who added a tool joins its line ("a@x · Added by Bob"), so the
        // row keeps one line.
        lineSuffix: addedBy ? (tool) => addedBy(tool.id) : undefined,
      }),
    [
      addedBy,
      attachedLine,
      catalog,
      connections,
      deviceOnline,
      kinds.items,
      listed,
      t,
    ],
  );

  // The reader's connections behind an offered tool that need signing in.
  const broken = useMemo(
    () =>
      onReconnect
        ? connections.filter(connectionNeedsSignIn).flatMap((connection) => {
            const own = offered.filter(
              (tool) => tool.connection_id === connection.id,
            );
            if (own.length === 0) return [];
            return [
              {
                connection,
                mcpToolId: own.find((tool) => tool.name === 'mcp_tool')?.id,
              },
            ];
          })
        : [],
    [connections, offered, onReconnect],
  );

  return (
    <>
      <MultiSelectPopover
        open={open}
        onOpenChange={onOpenChange}
        title={t('settings.tools.label')}
        items={items}
        // What is picked when it opens comes first (an attached tool the
        // reader can't list included); a lone group needs no heading.
        selectedFirst
        loneGroupHeading={false}
        filters={kinds.filters}
        selectedIds={selectedIds}
        onToggle={onToggle}
        searchPlaceholder={t('settings.tools.searchPlaceholder')}
        emptyMessage={t('settings.tools.noToolsFound')}
        footer={
          // A sign-in notice goes above the Go to Tools row.
          <div className="flex flex-col gap-3">
            {broken.length > 0 && onReconnect ? (
              <SignInAgainNotice
                connections={broken.map(({ connection }) => connection)}
                onReconnect={(ref) => {
                  const entry = broken.find(
                    (item) => item.connection.id === ref.id,
                  );
                  if (!entry) return;
                  onOpenChange(false);
                  onReconnect(entry.connection, entry.mcpToolId);
                }}
              />
            ) : null}
            <PickerFooter
              to="/settings/tools"
              linkLabel={t('settings.tools.manageTools')}
              onNavigate={(event) => {
                onOpenChange(false);
                onNavigate(event);
              }}
              actionLabel={t('settings.tools.addTool')}
              onAction={() => {
                onOpenChange(false);
                setAddToolState('ACTIVE');
              }}
            />
          </div>
        }
        trigger={trigger}
      />
      <AddToolModal
        message={t('settings.tools.selectToolSetup')}
        modalState={addToolState}
        setModalState={setAddToolState}
        getUserTools={onReloadTools}
        onToolsCreated={onToolsCreated}
        onNavigate={onLeaveTo}
      />
    </>
  );
}
