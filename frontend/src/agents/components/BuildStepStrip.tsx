import { ArrowRight } from 'lucide-react';

import { BottomTintReset } from '@/components/ui/bar-tint-reset';
import { Button } from '@/components/ui/button';

/**
 * The phone's in-page strip while the drafter's sheet steps aside after a
 * step: the whole strip is a stretched button that brings the sheet back
 * (Card `interactive="within"`'s recipe), with the step's Next lifted over it.
 * Fixed to the bottom edge below `lg`; Safari's bottom bar is re-sampled
 * when it goes.
 *
 * Args:
 *   title: What to do ("Check Basics").
 *   line: Where the build stands ("Step 1 of 4 · Basics").
 *   nextLabel: Next's label ("Next", "Finish").
 *   onOpen: Brings the sheet back.
 *   onNext: Runs the step's Next.
 */
export function BuildStepStrip({
  title,
  line,
  nextLabel,
  onOpen,
  onNext,
}: {
  title: string;
  line: string;
  nextLabel: string;
  onOpen: () => void;
  onNext: () => void;
}) {
  return (
    <div
      data-slot="build-step-strip"
      className="bg-background border-border hover:bg-accent has-[>button:focus-visible]:ring-ring/50 pb-safe fixed inset-x-0 bottom-0 z-20 flex items-center gap-3 border-t px-4 pt-3 transition-colors has-[>button:focus-visible]:ring-3 has-[>button:focus-visible]:ring-inset lg:hidden"
    >
      <BottomTintReset />
      <button
        type="button"
        onClick={onOpen}
        className="flex min-w-0 flex-1 cursor-pointer flex-col text-left outline-none after:absolute after:inset-0"
      >
        <span className="truncate text-sm font-medium" title={title}>
          {title}
        </span>
        <span className="text-muted-foreground truncate text-xs" title={line}>
          {line}
        </span>
      </button>
      {/* Lifted over the stretched button, and out of the strip's focus
          ring, which follows the stretched button alone. */}
      <div className="relative z-10 shrink-0">
        <Button type="button" size="sm" shape="pill" onClick={onNext}>
          {nextLabel}
          <ArrowRight />
        </Button>
      </div>
    </div>
  );
}
