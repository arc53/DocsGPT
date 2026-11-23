// Display names for the Swagger document's tags. The REST API reference page
// (components/ApiReference.jsx) and the generated endpoint pages (lib/openapi.js)
// both title their groups with these.

const GROUP_TITLES = {
  admin: 'Admin',
  agents_folders: 'Agent folders',
  mcp_apps: 'MCP apps',
  me: 'Current user',
  tokens: 'Personal access tokens',
  workflow_runs: 'Workflow runs',
};

/**
 * The display name of a Swagger tag.
 *
 * @param {string} name The tag name, such as `agents_folders`.
 * @returns {string} Its title, such as `Agent folders`.
 */
export function groupTitle(name) {
  if (GROUP_TITLES[name]) return GROUP_TITLES[name];
  const words = name.replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * Sentence case for a description that may lack its final full stop.
 *
 * @param {string} text A description from the code.
 * @returns {string} The text, ending in punctuation.
 */
export function sentence(text) {
  const trimmed = text.trim();
  return /[.!?)]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}
