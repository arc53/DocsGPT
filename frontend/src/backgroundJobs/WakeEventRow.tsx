import { BellRing, ChevronDown } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../components/ui/button';
import { cn } from '@/lib/utils';

import { wakeLabelKey, wakeTitle, type WakeInfo } from './kinds';

/**
 * A continuation turn's prompt is the event that woke the agent, not
 * something the user wrote: a compact system row ("Background job
 * finished: …") with the full event text behind a toggle.
 */
export default function WakeEventRow({
  wake,
  prompt,
  className,
}: {
  wake: WakeInfo;
  prompt: string;
  className?: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const title = wakeTitle(prompt);
  const more = wake.count > 1 ? wake.count - 1 : 0;

  return (
    <div
      className={cn('flex w-full min-w-0 flex-col', className)}
      data-testid="wake-event-row"
    >
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="ml-3.5 w-fit max-w-full justify-start"
      >
        <BellRing aria-hidden className="text-muted-foreground" />
        <span className="text-muted-foreground shrink-0">
          {t(wakeLabelKey(wake.source))}
        </span>
        {title && (
          <span
            className="text-muted-foreground/70 min-w-0 truncate"
            title={title}
          >
            {title}
          </span>
        )}
        {more > 0 && (
          <span className="text-muted-foreground shrink-0 text-xs">
            {t('backgroundJobs.wake.more', { count: more })}
          </span>
        )}
        <ChevronDown
          aria-hidden
          className={cn(
            'text-muted-foreground shrink-0 transition-transform duration-200',
            open ? 'rotate-180' : '',
          )}
        />
      </Button>
      {open && (
        <pre className="bg-muted text-muted-foreground mt-2 mr-5 ml-6 max-h-72 overflow-auto rounded-xl px-4 py-3 font-mono text-xs whitespace-pre-wrap">
          {prompt}
        </pre>
      )}
    </div>
  );
}
