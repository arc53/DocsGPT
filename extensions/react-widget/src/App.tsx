import React from 'react';
import { DocsGPTWidget } from './components/DocsGPTWidget';
import { SearchBar } from './components/SearchBar';
export const App = () => {
  return (
    <div>
      <SearchBar showMicButton />
      <DocsGPTWidget
        allowedFileExtensions={['.pdf', '.md', '.txt', '.docx', '.png', '.jpg']}
        showMicButton
        suggestedQuestions={[
          'How do I run DocsGPT locally?',
          'Which LLM providers can I use?',
          'How do I add the chat widget to my site?',
        ]}
      />
    </div>
  );
};
