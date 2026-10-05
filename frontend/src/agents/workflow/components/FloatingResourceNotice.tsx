import { TriangleAlert } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';

import { formatCount } from '../../../utils/dateTimeUtils';

type FloatingResourceNoticeProps = {
  /** Stopped node resources; nothing floats without one. */
  stoppedCount: number;
  /**
   * Step aside while something else floats in the same corner (the publish
   * errors); the notice keeps its open or closed state.
   */
  hidden?: boolean;
  /** The notice, given the function that closes it (its own close button). */
  children: (close: () => void) => ReactNode;
};

/**
 * The stopped-resources warning floating over the workflow canvas: the Alert
 * sits right on an opaque card (the floating-Alert recipe the publish errors
 * use), with its close button inside. Closing leaves a chip that says how
 * many items aren't running and opens it again.
 */
export default function FloatingResourceNotice({
  stoppedCount,
  hidden = false,
  children,
}: FloatingResourceNoticeProps) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(true);

  if (stoppedCount === 0 || hidden) return null;

  if (!open) {
    return (
      <div className="bg-card absolute top-4 left-4 z-20 rounded-full shadow-md">
        <Button
          type="button"
          variant="outline"
          size="sm"
          shape="pill"
          onClick={() => setOpen(true)}
        >
          <TriangleAlert className="text-warning" />
          {t('agents.form.resourceStates.chip', {
            formatted: formatCount(stoppedCount, i18n.language),
          })}
        </Button>
      </div>
    );
  }

  return (
    <div className="bg-card absolute top-4 left-4 z-20 w-md max-w-[calc(100%-2rem)] rounded-xl shadow-md">
      {children(() => setOpen(false))}
    </div>
  );
}
