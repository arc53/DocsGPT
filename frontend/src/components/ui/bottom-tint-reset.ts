import * as React from 'react';

// Tested on iPhone (Safari 26, Low Power Mode too): in the app 6px works and
// 4px doesn't (4px was enough on a bare test page, 2px never). One painted
// frame is enough; a 16ms timer isn't, because it can fire before a paint
// (Low Power Mode drops the refresh rate), so the strip lives for one frame.

/**
 * Makes iOS Safari re-colour its bottom bar from the page.
 *
 * Safari 26 takes the bottom bar's colour from a fixed element that appears on
 * the bottom edge (a bottom sheet turns it `bg-card`) and doesn't change it
 * back when that element goes away, or when an existing element changes
 * colour. A page-coloured strip that appears briefly on the edge makes Safari
 * sample again. The strip is 6px, no taller than the gap under the composer,
 * so it covers only background of its own colour. It has to be on top: a
 * strip behind the content, transparent or at `opacity-0` isn't sampled.
 */
function resetBottomTint(): void {
  const strip = document.createElement('div');
  strip.dataset.slot = 'bottom-tint-reset';
  strip.setAttribute('aria-hidden', 'true');
  strip.className =
    'bg-background pointer-events-none fixed inset-x-0 bottom-0 z-50 h-1.5';
  document.body.appendChild(strip);
  // The first frame paints the strip; remove it on the next.
  requestAnimationFrame(() => requestAnimationFrame(() => strip.remove()));
}

/**
 * Renders nothing; resets Safari's bottom bar when it unmounts. Put it inside
 * a bottom sheet's Radix Content, which unmounts after its exit animation.
 */
function BottomTintReset(): null {
  React.useEffect(() => resetBottomTint, []);
  return null;
}

export { BottomTintReset, resetBottomTint };
