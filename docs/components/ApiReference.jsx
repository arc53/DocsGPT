// Renders the REST API reference from docs/data/swagger.json at build time.
// The snapshot is generated from the backend (python -m docsgpt.api.reference --write);
// this is a server component, so the JSON never reaches the browser bundle.
import spec from '../data/swagger.json';
import { useMDXComponents } from '../mdx-components';

const METHOD_ORDER = ['get', 'post', 'put', 'patch', 'delete'];

const METHOD_COLORS = {
  get: '#2563eb',
  post: '#16a34a',
  put: '#d97706',
  patch: '#9333ea',
  delete: '#dc2626',
};

const GROUP_TITLES = {
  admin: 'Admin',
  agents_folders: 'Agent folders',
  me: 'Current user',
  tokens: 'Personal access tokens',
};

function groupTitle(name) {
  if (GROUP_TITLES[name]) return GROUP_TITLES[name];
  const words = name.replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function slug(text) {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

function refName(ref) {
  return ref.split('/').pop();
}

function typeLabel(schema) {
  if (!schema) return '';
  if (schema.$ref) return refName(schema.$ref);
  if (schema.type === 'array') return `array of ${typeLabel(schema.items) || 'any'}`;
  return schema.type || 'any';
}

// Descriptions in the code rarely end in a full stop; add one so the notes read as sentences.
function sentence(text) {
  const trimmed = text.trim();
  return /[.!?)]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

function fieldNotes(schema) {
  const notes = [];
  if (schema.description) notes.push(sentence(schema.description));
  if (schema.enum) notes.push(`One of: ${schema.enum.join(', ')}.`);
  if (schema.default !== undefined) notes.push(`Default: ${JSON.stringify(schema.default)}.`);
  return notes.join(' ');
}

// Operations grouped by their first tag, in the order the backend registers them.
function groupOperations() {
  const groups = new Map();
  for (const tag of spec.tags || []) {
    if (!groups.has(tag.name)) groups.set(tag.name, { description: tag.description, operations: [] });
  }
  for (const [path, item] of Object.entries(spec.paths)) {
    for (const method of METHOD_ORDER) {
      const operation = item[method];
      if (!operation) continue;
      const tag = (operation.tags && operation.tags[0]) || 'default';
      if (!groups.has(tag)) groups.set(tag, { operations: [] });
      const parameters = [...(item.parameters || []), ...(operation.parameters || [])];
      groups.get(tag).operations.push({ path, method, operation, parameters });
    }
  }
  return [...groups.entries()].filter(([, group]) => group.operations.length > 0);
}

function TokenAccess({ operation, components }) {
  const { code: Code } = components;
  if (operation['x-pat-denied']) {
    return <>Not available to personal access tokens</>;
  }
  const scopes = operation['x-pat-scopes'] || [];
  if (scopes.length === 0) return <>Any valid personal access token</>;
  return (
    <>
      Token scope:{' '}
      {scopes.map((scope, index) => (
        <span key={scope}>
          {index > 0 && ' or '}
          <Code>{scope}</Code>
        </span>
      ))}
    </>
  );
}

function ParameterTable({ parameters, components }) {
  const { table: Table, tr: Tr, th: Th, td: Td, code: Code } = components;
  return (
    <Table>
      <thead>
        <Tr>
          <Th>Parameter</Th>
          <Th>In</Th>
          <Th>Type</Th>
          <Th>Required</Th>
          <Th>Description</Th>
        </Tr>
      </thead>
      <tbody>
        {parameters.map((parameter) => (
          <Tr key={`${parameter.in}-${parameter.name}`}>
            <Td><Code>{parameter.name}</Code></Td>
            <Td>{parameter.in}</Td>
            <Td>{typeLabel(parameter)}</Td>
            <Td>{parameter.required ? 'yes' : 'no'}</Td>
            <Td>{fieldNotes(parameter)}</Td>
          </Tr>
        ))}
      </tbody>
    </Table>
  );
}

function BodyTable({ schema, components }) {
  const { table: Table, tr: Tr, th: Th, td: Td, code: Code, p: P } = components;
  const name = schema.$ref ? refName(schema.$ref) : null;
  const model = name ? spec.definitions[name] : schema;
  const properties = Object.entries((model && model.properties) || {});
  const required = new Set((model && model.required) || []);
  if (properties.length === 0) {
    return <P>JSON body{name ? <> (<Code>{name}</Code>)</> : null}.</P>;
  }
  return (
    <>
      <P>JSON body{name ? <> (<Code>{name}</Code>)</> : null}:</P>
      <Table>
        <thead>
          <Tr>
            <Th>Field</Th>
            <Th>Type</Th>
            <Th>Required</Th>
            <Th>Description</Th>
          </Tr>
        </thead>
        <tbody>
          {properties.map(([field, property]) => (
            <Tr key={field}>
              <Td><Code>{field}</Code></Td>
              <Td>{typeLabel(property)}</Td>
              <Td>{required.has(field) ? 'yes' : 'no'}</Td>
              <Td>{fieldNotes(property)}</Td>
            </Tr>
          ))}
        </tbody>
      </Table>
    </>
  );
}

function Operation({ path, method, operation, parameters, components }) {
  const { h3: H3, p: P, code: Code } = components;
  const body = parameters.find((parameter) => parameter.in === 'body');
  const others = parameters.filter((parameter) => parameter.in !== 'body');
  const summary = operation.summary || operation.description;
  const details = operation.summary && operation.description ? operation.description : null;
  return (
    <section>
      <H3 id={slug(`${method} ${path}`)}>
        <span style={{ color: METHOD_COLORS[method], fontFamily: 'monospace', marginInlineEnd: '0.5em' }}>
          {method.toUpperCase()}
        </span>
        <Code>{path}</Code>
      </H3>
      {summary && <P>{sentence(summary)}</P>}
      {details && <P>{sentence(details)}</P>}
      <P>
        <TokenAccess operation={operation} components={components} />
      </P>
      {others.length > 0 && <ParameterTable parameters={others} components={components} />}
      {body && <BodyTable schema={body.schema} components={components} />}
    </section>
  );
}

export function ApiReferenceIndex() {
  const { ul: Ul, li: Li, a: A } = useMDXComponents();
  return (
    <Ul>
      {groupOperations().map(([name, group]) => (
        <Li key={name}>
          <A href={`#${slug(`group ${name}`)}`}>{groupTitle(name)}</A> ({group.operations.length})
        </Li>
      ))}
    </Ul>
  );
}

export function ApiReference() {
  const components = useMDXComponents();
  const { h2: H2, p: P } = components;
  return (
    <>
      {groupOperations().map(([name, group]) => (
        <section key={name}>
          <H2 id={slug(`group ${name}`)}>{groupTitle(name)}</H2>
          {group.description && <P>{sentence(group.description)}</P>}
          {group.operations.map((entry) => (
            <Operation key={`${entry.method} ${entry.path}`} {...entry} components={components} />
          ))}
        </section>
      ))}
    </>
  );
}
