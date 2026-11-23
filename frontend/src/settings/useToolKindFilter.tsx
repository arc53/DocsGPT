import { useCallback, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import {
  selectConnections,
  selectConnectorCatalog,
} from '../connectors/connectorsSlice';
import { usePickerKindFilter } from '../hooks/usePickerKindFilter';
import {
  TOOL_KINDS,
  toolKindLabel,
  toolKindOf,
  type GroupableTool,
  type ToolKindFilter,
} from './toolGroups';

/**
 * A tool picker's kind filter (`usePickerKindFilter` with the tool groups:
 * Included · Added · Services · Custom), the same split as the Tools page
 * track: the xs track past `PICKER_FILTER_MIN_ITEMS` tools, opening on All
 * each time the picker opens.
 *
 * Args:
 *   tools: The picker's tools.
 *   open: Whether the picker is open.
 *
 * Returns:
 *   `kind`, the `tools` of that kind, and `filters`, the track to pass as
 *   the picker's `filters` (null while hidden).
 */
export function useToolKindFilter<T extends GroupableTool>(
  tools: readonly T[],
  open: boolean,
): { kind: ToolKindFilter; tools: T[]; filters: ReactNode } {
  const { t } = useTranslation();
  const connections = useSelector(selectConnections);
  const catalog = useSelector(selectConnectorCatalog);
  const matches = useCallback(
    (kind: ToolKindFilter, tool: T) =>
      kind === 'all' || toolKindOf(tool, connections, catalog) === kind,
    [connections, catalog],
  );
  const { kind, items, filters } = usePickerKindFilter(tools, open, {
    kinds: TOOL_KINDS,
    matches,
    labelOf: (k) => toolKindLabel(t, k),
    ariaLabel: t('settings.tools.kindFilterLabel'),
  });
  return { kind, tools: items, filters };
}
