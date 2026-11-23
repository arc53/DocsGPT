import { Tab as FumadocsTab, Tabs } from 'fumadocs-ui/components/tabs';
import defaultMdxComponents from 'fumadocs-ui/mdx';

import { Mermaid } from './components/Mermaid';

/**
 * A tab panel that stays in the HTML while another tab is selected, so its
 * text and headings are crawled, searchable and reachable by #anchor links.
 *
 * @param {Record<string, unknown>} props Fumadocs Tab props.
 * @returns {import('react').JSX.Element} The tab panel.
 */
function Tab(props) {
  return <FumadocsTab keepMounted {...props} />;
}

/**
 * Numbered steps: each `### heading` inside <Steps> starts a step.
 *
 * @param {{children: import('react').ReactNode}} props The step headings and their content.
 * @returns {import('react').JSX.Element} The steps.
 */
function Steps({ children }) {
  return <div className="fd-steps [&_h3]:fd-step">{children}</div>;
}

/**
 * The components every page can use without importing them: Fumadocs UI's
 * (Callout, Cards/Card, the code blocks, headings, tables), Tabs/Tab, Steps,
 * and Mermaid for ```mermaid code blocks.
 *
 * Plain HTML elements are included by name, so components/ApiReference.jsx and
 * components/McpPresets.jsx can render with the same mapping a page uses.
 *
 * @param {Record<string, unknown>} [components] Overrides for this render.
 * @returns {Record<string, unknown>} The MDX component map.
 */
export function getMDXComponents(components) {
  return {
    p: 'p',
    ul: 'ul',
    li: 'li',
    tr: 'tr',
    th: 'th',
    td: 'td',
    code: 'code',
    ...defaultMdxComponents,
    Tab,
    Tabs,
    Steps,
    Mermaid,
    ...components,
  };
}

export const useMDXComponents = getMDXComponents;
