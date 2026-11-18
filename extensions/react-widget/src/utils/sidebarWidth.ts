/** The sidebar's width rules, in CSS pixels. */
export const SIDEBAR_MIN_WIDTH = 320;
export const SIDEBAR_MAX_WIDTH = 720;
/** The page keeps at least 30% of the window. */
const SIDEBAR_MAX_SHARE = 0.7;
export const SIDEBAR_DEFAULT_WIDTH = 420;
/** Arrow-key steps on the resize handle; the larger one with Shift. */
export const SIDEBAR_STEP = 16;
export const SIDEBAR_BIG_STEP = 64;

/** `min(720px, 70vw)`, never below the minimum. */
export const sidebarMaxWidth = (viewportWidth: number) =>
  Math.max(
    SIDEBAR_MIN_WIDTH,
    Math.min(SIDEBAR_MAX_WIDTH, Math.floor(viewportWidth * SIDEBAR_MAX_SHARE)),
  );

export const clampSidebarWidth = (width: number, viewportWidth: number) =>
  Math.round(
    Math.min(
      Math.max(width, SIDEBAR_MIN_WIDTH),
      sidebarMaxWidth(viewportWidth),
    ),
  );

/** A stored or host-supplied width, or null when it isn't a usable number. */
export const parseSidebarWidth = (value: unknown): number | null => {
  const width = typeof value === 'string' ? Number(value) : value;
  return typeof width === 'number' && Number.isFinite(width) && width > 0
    ? Math.round(width)
    : null;
};

/**
 * The width an arrow, Home or End key moves to, or null for other keys.
 * Arrows move the edge itself, so which one widens depends on the side.
 */
export const sidebarWidthForKey = (
  key: string,
  shiftKey: boolean,
  side: 'left' | 'right',
  width: number,
  viewportWidth: number,
): number | null => {
  const step = shiftKey ? SIDEBAR_BIG_STEP : SIDEBAR_STEP;
  const widen = side === 'right' ? 'ArrowLeft' : 'ArrowRight';
  const narrow = side === 'right' ? 'ArrowRight' : 'ArrowLeft';
  let next: number;
  if (key === widen) next = width + step;
  else if (key === narrow) next = width - step;
  else if (key === 'Home') next = SIDEBAR_MIN_WIDTH;
  else if (key === 'End') next = sidebarMaxWidth(viewportWidth);
  else return null;
  return clampSidebarWidth(next, viewportWidth);
};
