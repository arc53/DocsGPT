import React from 'react';
import { DocsGPTWidget } from './components/DocsGPTWidget';
import { SearchBar } from './components/SearchBar';
import type { WidgetController, WidgetEvent } from './types/index';

// Try options from the URL, e.g. `?locale=de&theme=light&size=small`.
const params = new URLSearchParams(window.location.search);
const locale = params.get('locale') ?? undefined;
const theme = params.get('theme') === 'light' ? 'light' : 'dark';
const size = (['small', 'medium', 'large'] as const).find(
  (option) => option === params.get('size'),
);
const apiKey = params.get('apiKey') ?? undefined;

const logEvent = (event: WidgetEvent) => console.info('[docsgpt]', event);

const toolbarStyle: React.CSSProperties = {
  position: 'fixed',
  top: 72,
  left: 16,
  display: 'flex',
  flexWrap: 'wrap',
  gap: 8,
};

export const App = () => {
  // The JavaScript API through a ref; events are logged to the console.
  const widget = React.useRef<WidgetController>(null);
  return (
    <div>
      <SearchBar
        showMicButton
        locale={locale}
        theme={theme}
        apiKey={apiKey}
        onEvent={logEvent}
      />
      <div style={toolbarStyle}>
        <button type="button" onClick={() => widget.current?.toggle()}>
          Toggle
        </button>
        <button
          type="button"
          onClick={() =>
            widget.current?.ask('How do I add the chat widget to my site?')
          }
        >
          Ask
        </button>
        <button
          type="button"
          onClick={() =>
            widget.current?.ask('Which LLM providers can I use?', {
              send: false,
            })
          }
        >
          Fill
        </button>
      </div>
      <DocsGPTWidget
        ref={widget}
        allowedFileExtensions={['.pdf', '.md', '.txt', '.docx', '.png', '.jpg']}
        showMicButton
        locale={locale}
        theme={theme}
        size={size}
        apiKey={apiKey}
        onEvent={logEvent}
        suggestedQuestions={[
          'How do I run DocsGPT locally?',
          'Which LLM providers can I use?',
          'How do I add the chat widget to my site?',
        ]}
      />
    </div>
  );
};
