import React from 'react';
import {
  clampSidebarWidth,
  parseSidebarWidth,
  sidebarMaxWidth,
  sidebarWidthForKey,
  SIDEBAR_MIN_WIDTH,
} from '../utils/sidebarWidth';
import { readStorage, writeStorage } from '../utils/conversationStore';
import { useClientLayoutEffect } from './useClientLayoutEffect';

/** The custom property the sidebar's width is read from. */
export const SIDEBAR_WIDTH_VAR = '--dgpt-sidebar-width';

// Over the whole page while dragging: links and text fields would otherwise
// swap the cursor, and the drag would select the host's text.
const DRAG_STYLE =
  '*{cursor:col-resize!important;user-select:none!important;-webkit-user-select:none!important}';

const viewportWidth = () =>
  typeof window === 'undefined' ? Infinity : window.innerWidth;

interface Drag {
  pointerId: number;
  startX: number;
  startWidth: number;
  width: number;
  frame: number;
  style: HTMLStyleElement | null;
}

/**
 * The sidebar's width: the host's default until the visitor drags the edge
 * or uses the arrow keys, kept under `storageKey` when there is one. The
 * width shown is clamped to the window, so a narrower window shrinks the
 * sidebar without forgetting the visitor's choice.
 */
export function useSidebarResize({
  active,
  side,
  defaultWidth,
  storageKey,
  containerRef,
}: {
  active: boolean;
  side: 'left' | 'right';
  defaultWidth: number;
  storageKey: string | null;
  containerRef: React.RefObject<HTMLElement | null>;
}) {
  const [chosenWidth, setChosenWidth] = React.useState<number | null>(null);
  const [viewport, setViewport] = React.useState(viewportWidth);
  const [dragging, setDragging] = React.useState(false);
  const dragRef = React.useRef<Drag | null>(null);
  const handleRef = React.useRef<HTMLDivElement | null>(null);

  // A different agent starts from its own stored width, or the default.
  React.useEffect(() => {
    setChosenWidth(
      storageKey ? parseSidebarWidth(readStorage(storageKey)) : null,
    );
  }, [storageKey]);

  React.useEffect(() => {
    if (!active) return;
    const update = () => setViewport(viewportWidth());
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, [active]);

  const width = clampSidebarWidth(chosenWidth ?? defaultWidth, viewport);

  const choose = (next: number) => {
    setChosenWidth(next);
    if (storageKey) writeStorage(storageKey, String(next));
  };

  const endDrag = () => {
    const drag = dragRef.current;
    if (!drag) return;
    if (drag.frame) window.cancelAnimationFrame(drag.frame);
    // The last move may still be waiting for its frame.
    paint();
    dragRef.current = null;
    drag.style?.remove();
    setDragging(false);
    if (drag.width !== drag.startWidth) choose(drag.width);
  };

  // Closed, or gone full screen, mid-drag: the handle is unmounted and its
  // pointer events stop, so end the drag here rather than leave the page's
  // cursor and selection locked.
  React.useEffect(() => {
    if (!active) endDrag();
  }, [active]);
  // Unmounted mid-drag (destroy, route change): unlock the page and keep the
  // width, through the latest endDrag so it writes under the current key.
  const endDragRef = React.useRef(endDrag);
  useClientLayoutEffect(() => {
    endDragRef.current = endDrag;
  });
  React.useEffect(() => () => endDragRef.current(), []);

  // A drag whose handle lost the pointer without telling us.
  const isStale = (drag: Drag) =>
    !handleRef.current?.hasPointerCapture?.(drag.pointerId);

  // Written straight to the nodes, so a long conversation isn't re-rendered
  // per pointer move; the width is committed once the drag ends.
  const paint = () => {
    const drag = dragRef.current;
    if (!drag) return;
    drag.frame = 0;
    containerRef.current?.style.setProperty(
      SIDEBAR_WIDTH_VAR,
      `${drag.width}px`,
    );
    handleRef.current?.setAttribute('aria-valuenow', String(drag.width));
  };

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (dragRef.current && isStale(dragRef.current)) endDrag();
    if (event.button !== 0 || dragRef.current) return;
    // Keeps the press from starting a text selection.
    event.preventDefault();
    // Captured, the drag keeps its events over iframes and outside the window.
    event.currentTarget.setPointerCapture(event.pointerId);
    let style: HTMLStyleElement | null = null;
    try {
      style = document.createElement('style');
      style.textContent = DRAG_STYLE;
      document.head.appendChild(style);
    } catch {
      style = null;
    }
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: width,
      width,
      frame: 0,
      style,
    };
    setDragging(true);
  };

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || event.pointerId !== drag.pointerId) return;
    const delta =
      side === 'right'
        ? drag.startX - event.clientX
        : event.clientX - drag.startX;
    drag.width = clampSidebarWidth(drag.startWidth + delta, viewportWidth());
    if (!drag.frame) drag.frame = window.requestAnimationFrame(paint);
  };

  const onPointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.pointerId === dragRef.current?.pointerId) endDrag();
  };

  // Cancelled by the browser (a touch turned into a scroll, a lost window):
  // keep what the visitor saw.
  const onLostPointerCapture = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.pointerId === dragRef.current?.pointerId) endDrag();
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (dragRef.current) {
      if (!isStale(dragRef.current)) return;
      endDrag();
    }
    const next = sidebarWidthForKey(
      event.key,
      event.shiftKey,
      side,
      width,
      viewport,
    );
    if (next === null) return;
    event.preventDefault();
    if (next !== width) choose(next);
  };

  return {
    width,
    dragging,
    handleProps: {
      ref: handleRef,
      role: 'separator',
      tabIndex: 0,
      'aria-orientation': 'vertical' as const,
      'aria-valuenow': width,
      'aria-valuemin': SIDEBAR_MIN_WIDTH,
      'aria-valuemax': sidebarMaxWidth(viewport),
      onPointerDown,
      onPointerMove,
      onPointerUp,
      onPointerCancel: onLostPointerCapture,
      onLostPointerCapture,
      onKeyDown,
    },
  };
}
