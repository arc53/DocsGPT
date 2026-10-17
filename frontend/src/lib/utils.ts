import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Class strings shared by the ui/ primitives, so every control spells the
// DESIGN.md focus, field and invalid rules the same way. Plain strings (not a
// Tailwind @utility) so the literal classes stay greppable and testable.

/** The keyboard focus ring (DESIGN.md "Focus ring"); fields add focus-visible:border-ring. */
export const focusRing = 'focus-visible:ring-3 focus-visible:ring-ring/50';

/** The red ring and border a control shows while aria-invalid is set. */
export const invalidState =
  'aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive';

/** The scrim behind every Modal, Dialog and Sheet: a light blurred dim, darker in dark mode. */
export const overlayScrim = 'bg-black/25 backdrop-blur-xs dark:bg-black/50';

/** The focus ring of a destructive button, red instead of the ring token. */
export const destructiveRing =
  'focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40';

/** The frame of a form field: a 1px input border, the field shadow and a quiet transition. */
export const fieldFrame =
  'border border-input shadow-xs transition-[color,box-shadow] outline-none';
