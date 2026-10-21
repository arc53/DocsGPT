//exports browser ready methods

import { createRoot } from 'react-dom/client';

import { DocsGPTWidget } from './components/DocsGPTWidget';
import { SearchBar } from './components/SearchBar';
import React from 'react';
import type {
  SearchBarInstance,
  SearchBarProps,
  WidgetController,
  WidgetInstance,
  WidgetProps,
} from './types/index';
import { callSafely, createEmitter } from './utils/events';

if (typeof window !== 'undefined') {
  const renderWidget = (
    elementId: string,
    props: WidgetProps = {},
  ): WidgetInstance => {
    const root = createRoot(document.getElementById(elementId) as HTMLElement);
    // Owned here rather than by React, so on() works before the first render.
    const emitter = createEmitter();
    let controller: WidgetController | null = null;
    // Calls made before React has rendered, replayed once it has.
    let queued: ((target: WidgetController) => void)[] = [];
    let expectedOpen = Boolean(props.defaultOpen);
    let destroyed = false;

    const run = (call: (target: WidgetController) => void) => {
      if (destroyed) return;
      if (controller) call(controller);
      else queued.push(call);
    };
    const attach = (instance: WidgetController | null) => {
      controller = instance;
      if (!instance) return;
      const calls = queued;
      queued = [];
      calls.forEach((call) => call(instance));
    };

    root.render(
      <DocsGPTWidget
        {...props}
        ref={attach}
        onEvent={(event) => {
          callSafely(props.onEvent, event);
          emitter.emit(event);
        }}
      />,
    );

    return {
      open: () => {
        expectedOpen = true;
        run((target) => target.open());
      },
      close: () => {
        expectedOpen = false;
        run((target) => target.close());
      },
      toggle: () => {
        expectedOpen = !expectedOpen;
        run((target) => target.toggle());
      },
      isOpen: () =>
        !destroyed && (controller ? controller.isOpen() : expectedOpen),
      focus: () => {
        expectedOpen = true;
        run((target) => target.focus());
      },
      ask: (question, options) => {
        expectedOpen = true;
        run((target) => target.ask(question, options));
      },
      newChat: () => run((target) => target.newChat()),
      clearHistory: () => run((target) => target.clearHistory()),
      on: emitter.on,
      off: emitter.off,
      destroy: () => {
        if (destroyed) return;
        destroyed = true;
        queued = [];
        emitter.clear();
        root.unmount();
        controller = null;
      },
    };
  };

  const renderSearchBar = (
    elementId: string,
    props: SearchBarProps = {},
  ): SearchBarInstance => {
    const root = createRoot(document.getElementById(elementId) as HTMLElement);
    root.render(<SearchBar {...props} />);
    let destroyed = false;
    return {
      destroy: () => {
        if (destroyed) return;
        destroyed = true;
        root.unmount();
      },
    };
  };

  (window as unknown as Record<string, unknown>).renderDocsGPTWidget =
    renderWidget;

  (window as unknown as Record<string, unknown>).renderSearchBar =
    renderSearchBar;
}

export { DocsGPTWidget, SearchBar };
