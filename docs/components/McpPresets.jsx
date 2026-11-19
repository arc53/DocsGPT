// Renders the curated MCP presets from docs/data/mcp-presets.json at build time.
// The file is generated from docsgpt/connectors/presets/mcp/*.yaml
// (python -m docsgpt.connectors.reference --write), so a new preset shows up
// here without an edit to a docs page. Server component: no browser bundle.
import presets from '../data/mcp-presets.json';
import { useMDXComponents } from '../mdx-components';

const SIGN_IN = {
  oauth: 'OAuth',
  none: 'None',
};

function accessLabel(capabilities) {
  const parts = [];
  if (capabilities.includes('sync')) parts.push('sync');
  if (capabilities.includes('read')) parts.push('read');
  if (capabilities.includes('write')) parts.push('write');
  return parts.join(', ');
}

export function McpPresetTable() {
  const { table: Table, tr: Tr, th: Th, td: Td, a: A } = useMDXComponents();
  return (
    <Table>
      <thead>
        <Tr>
          <Th>Preset</Th>
          <Th>What agents can do</Th>
          <Th>Sign-in</Th>
          <Th>Access</Th>
        </Tr>
      </thead>
      <tbody>
        {presets.map((preset) => (
          <Tr key={preset.key}>
            <Td>{preset.docs_url ? <A href={preset.docs_url}>{preset.name}</A> : preset.name}</Td>
            <Td>{preset.description}</Td>
            <Td>{SIGN_IN[preset.sign_in] || preset.sign_in}</Td>
            <Td>{accessLabel(preset.capabilities)}</Td>
          </Tr>
        ))}
      </tbody>
    </Table>
  );
}
