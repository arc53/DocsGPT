import React from 'react';
import { DocsGPTWidget } from './components/DocsGPTWidget';
import { SearchBar } from './components/SearchBar';

// Try options from the URL, e.g. `?locale=de&theme=light&size=small`.
const params = new URLSearchParams(window.location.search);
const locale = params.get('locale') ?? undefined;
const theme = params.get('theme') === 'light' ? 'light' : 'dark';
const size = (['small', 'medium', 'large'] as const).find(
  (option) => option === params.get('size'),
);

export const App = () => {
  return (
    <div>
      <SearchBar showMicButton locale={locale} theme={theme} />
      <DocsGPTWidget
        allowedFileExtensions={['.pdf', '.md', '.txt', '.docx', '.png', '.jpg']}
        showMicButton
        locale={locale}
        theme={theme}
        size={size}
        suggestedQuestions={[
          'How do I run DocsGPT locally?',
          'Which LLM providers can I use?',
          'How do I add the chat widget to my site?',
        ]}
      />
    </div>
  );
};
