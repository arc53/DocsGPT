import type {
  WidgetController,
  WidgetEvent,
  WidgetEventType,
} from '../types/index';

type AnyHandler = (event: WidgetEvent) => void;

// Omit per member, so the union stays discriminated.
type OmitEach<T, K extends PropertyKey> = T extends unknown
  ? Omit<T, K>
  : never;

/** A `WidgetEvent` before the widget stamps its `conversationId` on it. */
export type WidgetEventInit = OmitEach<WidgetEvent, 'conversationId'>;

/** Runs a host's handler; one that throws is logged and the widget carries on. */
export const callSafely = (
  handler: ((event: WidgetEvent) => void) | undefined,
  event: WidgetEvent,
) => {
  if (typeof handler !== 'function') return;
  try {
    handler(event);
  } catch (error) {
    console.error(`DocsGPT widget: a "${event.type}" handler threw`, error);
  }
};

export interface Emitter extends Pick<WidgetController, 'on' | 'off'> {
  emit: (event: WidgetEvent) => void;
  /** Drops every handler. */
  clear: () => void;
}

/** Per-type handler lists behind the controller's `on` / `off`. */
export const createEmitter = (): Emitter => {
  const handlers = new Map<WidgetEventType, Set<AnyHandler>>();
  const off: Emitter['off'] = (type, handler) => {
    handlers.get(type)?.delete(handler as AnyHandler);
  };
  return {
    on: (type, handler) => {
      if (typeof handler !== 'function') return () => undefined;
      let set = handlers.get(type);
      if (!set) {
        set = new Set();
        handlers.set(type, set);
      }
      set.add(handler as AnyHandler);
      return () => off(type, handler);
    },
    off,
    emit: (event) => {
      const set = handlers.get(event.type);
      // A copy, so a handler that unsubscribes mid-dispatch skips no one;
      // one removed by an earlier handler is skipped, as in the DOM.
      if (set)
        [...set].forEach((handler) => {
          if (set.has(handler)) callSafely(handler, event);
        });
    },
    clear: () => handlers.clear(),
  };
};
