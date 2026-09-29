import { TriangleAlert, X } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { IconButton } from '@/components/ui/icon-button';

type FloatingResourceNoticeProps = {
  /** Stopped node resources; a closed notice leaves a chip while any remain. */
  stoppedCount: number;
  /** The notice itself. */
  children: ReactNode;
};

/**
 * The resource notice floating over the workflow canvas. Closing it leaves
 * a chip that says how many items aren't running and opens it again.
 */
export default function FloatingResourceNotice({
  stoppedCount,
  children,
}: FloatingResourceNoticeProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(true);

  if (!open) {
    if (stoppedCount === 0) return null;
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
          {t('agents.form.resourceStates.chip', { count: stoppedCount })}
        </Button>
      </div>
    );
  }

  return (
    <div className="bg-card absolute top-4 left-4 z-20 max-h-[60%] w-md max-w-[calc(100%-2rem)] overflow-y-auto rounded-xl shadow-md">
      <div className="relative p-3 pr-10">
        {children}
        <div className="absolute top-2.5 right-2.5">
          <IconButton
            variant="ghost"
            size="icon-xs"
            onClick={() => setOpen(false)}
            label={t('agents.close')}
            icon={X}
          />
        </div>
      </div>
    </div>
  );
}
