import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

type SidebarLevelProps = {
  /** This panel's place in the hierarchy: 0 chats, 1 a section, 2 a record. */
  depth: number;
  /** The level on screen right now. */
  current: number;
  children: ReactNode;
  className?: string;
};

/**
 * One panel in the sidebar's navigation stack.
 *
 * Every panel is positioned from a single number — its depth relative to the
 * level on screen — so push and pop fall out of the same rule instead of
 * needing a direction to be tracked. A panel above the current level waits
 * off to the right; the current one sits at rest; ones below are parked just
 * off to the left. Changing level therefore animates both panels the right
 * way round, whichever way the user is going.
 *
 * The panel behind only travels a quarter of the width, so it trails the
 * incoming panel rather than marching with it — the cue that one sits on top
 * of the other rather than beside it. Each panel paints its own background
 * so it occludes the one behind while it slides.
 *
 * `visibility` is in the transition on purpose: CSS keeps an element visible
 * for the whole duration when either end of the transition is `visible`, so a
 * panel stays on screen while it leaves and only drops out of the tab order
 * once it has gone. Panels are never unmounted, which is what lets the chat
 * list keep its scroll position across a trip into settings.
 */
export default function SidebarLevel({
  depth,
  current,
  children,
  className,
}: SidebarLevelProps) {
  const offset = depth - current;

  return (
    <div
      aria-hidden={offset !== 0}
      className={cn(
        'bg-sidebar absolute inset-0 flex flex-col',
        'transition-[translate,opacity,visibility] duration-400',
        // Decelerating, and tuned against where the travel actually lands:
        // half the distance by ~65ms so the panel tracks the click, 90% by
        // ~180ms so the movement reads as movement, settled by ~300ms. A
        // sharper curve (the usual 0.32,0.72,0,1) covers 90% in 110ms at this
        // duration, which registers as a cut rather than a slide; an even
        // one (0.4,0,0.2,1) takes 105ms just to reach halfway and feels like
        // it is lagging behind the pointer.
        'ease-[cubic-bezier(0.25,0.8,0.25,1)] motion-reduce:transition-none',
        // The arriving panel carries a shadow off its leading edge, which
        // the container clips once it comes to rest — so the layering only
        // shows while there is layering to show.
        offset === 0 &&
          'visible translate-x-0 opacity-100 shadow-[-12px_0_24px_-6px_rgba(0,0,0,0.45)]',
        // Dimmed rather than faded out: at rest the panel in front covers it
        // completely, so there is nothing to hide, and keeping it legible
        // while it trails is the whole point of the shorter travel.
        offset < 0 && 'invisible -translate-x-1/4 opacity-50',
        offset > 0 && 'invisible translate-x-full opacity-100',
        className,
      )}
    >
      {children}
    </div>
  );
}
