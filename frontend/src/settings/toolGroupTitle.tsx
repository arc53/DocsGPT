import type { TFunction } from 'i18next';
import type { ReactNode } from 'react';

import ConnectorIcon from '../connectors/ConnectorIcon';
import { cn } from '@/lib/utils';
import { toolGroupLabel, type ToolGroup } from './toolGroups';

/**
 * A tool group's heading, the same on the Tools page and in both pickers:
 * Included, Added or Custom, or a service's icon and name. The account a
 * service's tool uses is on the tool's own line, never in the heading.
 *
 * Args:
 *   t: The translate function.
 *   group: The group.
 *   iconClassName: The service icon's size: `size-4` on the Tools page,
 *     `size-3.5` in a picker.
 *
 * Returns:
 *   The heading: plain text, or the icon and the name.
 */
export function toolGroupTitle(
  t: TFunction,
  group: Pick<ToolGroup<unknown>, 'kind' | 'service'>,
  iconClassName = 'size-4',
): ReactNode {
  const label = toolGroupLabel(t, group);
  if (group.kind !== 'service' || !group.service?.icon) return label;
  return (
    <span className="flex items-center gap-2">
      <ConnectorIcon
        icon={group.service.icon}
        className={cn('shrink-0', iconClassName)}
      />
      {label}
    </span>
  );
}
