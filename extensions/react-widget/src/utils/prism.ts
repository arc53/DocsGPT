/**
 * A private Prism instance for the answer's code blocks.
 *
 * Prism installs itself as `window.Prism` and, unless told it is manual,
 * highlights every `language-*` block on the page once the DOM is ready. On an
 * embedder's site that would restyle the host's own code and replace a Prism
 * the host loaded with its own plugins. The guard marks this copy manual
 * before it loads and hands `window.Prism` back afterwards; the grammars
 * register while this instance is the global, as they expect.
 */
import { restoreHostPrism } from './prismGuard';
import Prism from 'prismjs';
import 'prismjs/components/prism-python';
import 'prismjs/components/prism-typescript';
import 'prismjs/components/prism-jsx';
import 'prismjs/components/prism-tsx';
import 'prismjs/components/prism-json';
import 'prismjs/components/prism-bash';
import 'prismjs/components/prism-yaml';
import 'prismjs/components/prism-sql';

restoreHostPrism();

const ALIASES: Record<string, string> = {
  py: 'python',
  js: 'javascript',
  ts: 'typescript',
  sh: 'bash',
  shell: 'bash',
  zsh: 'bash',
  yml: 'yaml',
  html: 'markup',
  xml: 'markup',
};

/**
 * Highlights `code` as `language`, or returns null when there is no grammar
 * for it (the caller escapes the text instead).
 */
export const highlight = (code: string, language: string): string | null => {
  const name = ALIASES[language] ?? language;
  const grammar = Prism.languages[name];
  if (!grammar) return null;
  return Prism.highlight(code, grammar, name);
};
