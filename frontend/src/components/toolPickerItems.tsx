import type { TFunction } from 'i18next';

import ConnectorIcon from '../connectors/ConnectorIcon';
import { connectionNeedsSignIn } from '../connectors/connectorsSlice';
import { accountLine, connectorDescription } from '../connectors/i18n';
import { toolServiceOf } from '../connectors/toolService';
import type { Connection, ConnectorDefinition } from '../connectors/types';
import { toolGroupTitle } from '../settings/toolGroupTitle';
import { groupTools } from '../settings/toolGroups';
import { type AccessFields, isOwner } from '../utils/accessUtils';
import { getToolDisplayName } from '../utils/toolUtils';
import type { MultiSelectPopoverItem } from './MultiSelectPopover';
import ToolIcon from './ToolIcon';
import { Badge } from './ui/badge';

/** A tool as the pickers list it: a `/api/get_tools` row or an agent's tool summary. */
export type PickerTool = AccessFields & {
  id: string;
  name: string;
  displayName?: string | null;
  display_name?: string | null;
  customName?: string | null;
  description?: string | null;
  connection_id?: string | null;
  config?: unknown;
  default?: boolean;
  builtin?: boolean;
  shared_via?: string | null;
};

type ToolPickerOptions<T extends PickerTool> = {
  t: TFunction;
  /** The caller's own connections. */
  connections: Connection[];
  catalog: ConnectorDefinition[];
  /**
   * Remote devices' online state by device id. Left out while unknown: the
   * rows then show no status.
   */
  deviceOnline?: Map<string, boolean>;
  /** A row's line in place of the usual one (a tool the caller can't list). */
  lineFor?: (tool: T) => string | undefined;
  /**
   * Text joined to the end of a row's line with " · " ("Added by Lena" in
   * the agent builder), so the row keeps one line.
   */
  lineSuffix?: (tool: T) => string | null | undefined;
};

/**
 * The rows of a tool picker (the chat's and the agent builder's), in the
 * groups the Tools page uses. Each row has one line that tells it apart:
 * who shared it, else the account it uses, else the catalog text, with the
 * status badges (Reconnect, a device's Online or Offline) above that line.
 *
 * Args:
 *   tools: The tools.
 *   options: The caller's connections, the catalog, device status and an
 *     optional line override.
 *
 * Returns:
 *   The picker rows, in group order.
 */
export function toolPickerItems<T extends PickerTool>(
  tools: T[],
  {
    t,
    connections,
    catalog,
    deviceOnline,
    lineFor,
    lineSuffix,
  }: ToolPickerOptions<T>,
): MultiSelectPopoverItem[] {
  return groupTools(tools, connections, catalog).flatMap((group) => {
    const groupHeading = toolGroupTitle(t, group, 'size-3.5');
    return group.tools.map((tool) => {
      const service = toolServiceOf(tool, connections, catalog);
      const connection = service?.connection;
      const name = getToolDisplayName(tool);
      // The account is the row's line, so the " · account" the server adds
      // to tell accounts apart is dropped from the name (as on the Tools page).
      const label =
        connection && name.startsWith(`${connection.name} · `)
          ? connection.name
          : name;
      const connector = service?.connector;
      const catalogText =
        connector && connector.publisher !== 'custom'
          ? connectorDescription(t, connector)
          : tool.description || undefined;
      const sharedBy =
        !isOwner(tool) && tool.shared_via
          ? t('settings.tools.sharedBy', {
              interpolation: { escapeValue: false },
              team: tool.shared_via,
            })
          : undefined;
      const line =
        [
          lineFor?.(tool) ??
            sharedBy ??
            (connection ? accountLine(t, connection) : undefined) ??
            catalogText,
          lineSuffix?.(tool),
        ]
          .filter(Boolean)
          .join(' · ') || undefined;

      const badges = [];
      if (connectionNeedsSignIn(connection)) {
        badges.push(
          <Badge key="reconnect" variant="warning">
            {t('settings.connectors.status.reconnect')}
          </Badge>,
        );
      }
      const deviceId = (tool.config as { device_id?: string } | undefined)
        ?.device_id;
      if (tool.name === 'remote_device' && deviceOnline) {
        const online = deviceOnline.get(deviceId ?? '') ?? false;
        badges.push(
          <Badge key="device" variant={online ? 'success' : 'neutral'}>
            {online
              ? t('settings.devices.online')
              : t('settings.devices.offline')}
          </Badge>,
        );
      }

      const item: MultiSelectPopoverItem = {
        id: tool.id,
        label,
        icon: service?.icon ? (
          <ConnectorIcon icon={service.icon} className="size-5" />
        ) : (
          <ToolIcon name={tool.name} className="size-5" />
        ),
        group: group.key,
        groupHeading,
      };
      if (badges.length === 0) return { ...item, description: line };
      return {
        ...item,
        keywords: line ? [line] : undefined,
        descriptionNode: (
          <div className="flex flex-col items-start gap-0.5">
            <span className="mt-0.5 flex flex-wrap gap-1">{badges}</span>
            {line ? (
              <p
                className="text-muted-foreground w-full truncate text-xs"
                title={line}
              >
                {line}
              </p>
            ) : null}
          </div>
        ),
      };
    });
  });
}
