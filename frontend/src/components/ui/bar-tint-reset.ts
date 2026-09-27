import * as React from 'react';

// Tested on iPhone (Safari 26, Low Power Mode too). Bottom edge: in the app
// 6px works and 4px doesn't (4px was enough on a bare test page, 2px never).
// Top edge: 16px works, 6px doesn't. One painted frame is enough; a 16ms
// timer isn't, because it can fire before a paint (Low Power Mode drops the
// refresh rate), so each strip lives for one frame.

/**
 * Shows a page-coloured strip on one edge for a single painted frame. At most
 * one strip per edge at a time: every useDarkTheme consumer applies a theme
 * change, and one strip is enough.
 */
function flashStrip(edge: 'top' | 'bottom', className: string): void {
  const slot = `${edge}-tint-reset`;
  if (document.querySelector(`[data-slot="${slot}"]`)) return;
  const strip = document.createElement('div');
  strip.dataset.slot = slot;
  strip.setAttribute('aria-hidden', 'true');
  strip.className = className;
  document.body.appendChild(strip);
  // The first frame paints the strip; remove it on the next.
  requestAnimationFrame(() => requestAnimationFrame(() => strip.remove()));
}

/**
 * Makes iOS Safari re-colour its bottom bar from the page.
 *
 * Safari 26 takes the bottom bar's colour from a fixed element that appears on
 * the bottom edge (a bottom sheet turns it `bg-card`) and doesn't change it
 * back when that element goes away, or when the page changes colour (a theme
 * switch). A page-coloured strip that appears briefly on the edge makes Safari
 * sample again. The strip is 6px, no taller than the gap under the composer,
 * so it covers only background of its own colour. It has to be on top: a
 * strip behind the content, transparent or at `opacity-0` isn't sampled.
 */
function resetBottomTint(): void {
  flashStrip(
    'bottom',
    'bg-background pointer-events-none fixed inset-x-0 bottom-0 z-50 h-1.5',
  );
}

/**
 * Makes iOS Safari re-colour its top bar from the page, the same way as
 * `resetBottomTint`. Needed after a theme switch, when the top bar keeps the
 * old theme's colour. The strip is 16px, inside the phone top bar, which has
 * the same background.
 */
function resetTopTint(): void {
  flashStrip(
    'top',
    'bg-background pointer-events-none fixed inset-x-0 top-0 z-50 h-4',
  );
}

/**
 * Renders nothing; resets Safari's bottom bar when it unmounts. Put it inside
 * a bottom sheet's Radix Content, which unmounts after its exit animation.
 */
function BottomTintReset(): null {
  React.useEffect(() => resetBottomTint, []);
  return null;
}

export { BottomTintReset, resetBottomTint, resetTopTint };
