import { Radar } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { cn, focusRing } from '@/lib/utils';

import type { MonitorRange } from './types';

export type MonitorChipsProps = {
  monitors: MonitorRange[];
  onSelectMonitor: (monitor: MonitorRange) => void;
};

/**
 * The window's monitors as a row of chips, for the views without a time grid
 * to draw them as bars on (Agenda and Month). Each opens its monitor.
 */
export default function MonitorChips({
  monitors,
  onSelectMonitor,
}: MonitorChipsProps) {
  const { t } = useTranslation();
  if (monitors.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {monitors.map((monitor) => (
        <button
          key={monitor.monitor_id}
          type="button"
          onClick={() => onSelectMonitor(monitor)}
          className={cn(
            focusRing,
            'bg-muted hover:bg-accent inline-flex max-w-full items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium outline-none',
          )}
        >
          <Radar aria-hidden className="size-3 shrink-0" />
          <span className="truncate" title={monitor.description || undefined}>
            {monitor.description || t('monitors.untitled')}
          </span>
        </button>
      ))}
    </div>
  );
}
