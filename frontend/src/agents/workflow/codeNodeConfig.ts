import type { CodeNodeConfig } from '../types/workflow';

/**
 * Validate a parsed JSON schema object the same way the agent node does:
 * it must be a non-array object that declares a "type" or "schema" field.
 * Returns null when valid (or absent), otherwise a short error fragment.
 */
export function validateCodeJsonSchema(schema: unknown): string | null {
  if (schema === undefined || schema === null) return null;
  if (typeof schema !== 'object' || Array.isArray(schema)) {
    return 'must be a valid JSON object';
  }
  const schemaObject = schema as Record<string, unknown>;
  if (!('schema' in schemaObject) && !('type' in schemaObject)) {
    return 'must include either a "type" or "schema" field';
  }
  return null;
}

/**
 * Parse the raw json_schema textarea content. Returns the parsed schema (or
 * undefined when blank) and a validation error message when invalid.
 */
export function parseCodeJsonSchemaDraft(text: string): {
  schema: Record<string, unknown> | undefined;
  error: string | null;
} {
  if (text.trim() === '') {
    return { schema: undefined, error: null };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { schema: undefined, error: 'must be valid JSON' };
  }
  const error = validateCodeJsonSchema(parsed);
  if (error) {
    return { schema: undefined, error };
  }
  return { schema: parsed as Record<string, unknown>, error: null };
}

/** Split a newline/comma separated inputs textarea into a clean ref list. */
export function parseCodeInputs(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0);
}

/** Render an inputs list back into the textarea (one ref per line). */
export function stringifyCodeInputs(inputs: string[] | undefined): string {
  return (inputs || []).join('\n');
}

/** Default config applied when a fresh code node is dropped onto the canvas. */
export function createDefaultCodeConfig(): CodeNodeConfig {
  return {
    code: '',
    inputs: [],
  };
}

/**
 * Normalize an arbitrary loaded config (from a saved workflow) into the editor
 * shape, tolerating missing/extra fields so existing workflows keep loading.
 */
export function normalizeCodeConfig(
  raw: Record<string, unknown> | undefined,
): CodeNodeConfig {
  const source = raw || {};
  const config: CodeNodeConfig = {
    code: typeof source.code === 'string' ? source.code : '',
    inputs: Array.isArray(source.inputs)
      ? source.inputs.filter(
          (entry): entry is string => typeof entry === 'string',
        )
      : [],
  };
  if (typeof source.output_variable === 'string' && source.output_variable) {
    config.output_variable = source.output_variable;
  }
  if (typeof source.timeout === 'number' && Number.isFinite(source.timeout)) {
    config.timeout = source.timeout;
  }
  if (
    source.json_schema &&
    typeof source.json_schema === 'object' &&
    !Array.isArray(source.json_schema)
  ) {
    config.json_schema = source.json_schema as Record<string, unknown>;
  }
  return config;
}

/**
 * Serialize the editor config into the exact CodeNodeConfig shape the backend
 * expects. Optional fields are omitted when empty so the payload stays clean.
 */
export function serializeCodeConfig(
  config: CodeNodeConfig | undefined,
): CodeNodeConfig {
  const source = config || createDefaultCodeConfig();
  const serialized: CodeNodeConfig = {
    code: source.code || '',
    inputs: (source.inputs || []).filter(
      (entry) => typeof entry === 'string' && entry.trim() !== '',
    ),
  };
  if (source.output_variable && source.output_variable.trim() !== '') {
    serialized.output_variable = source.output_variable.trim();
  }
  if (typeof source.timeout === 'number' && Number.isFinite(source.timeout)) {
    serialized.timeout = source.timeout;
  }
  if (
    source.json_schema &&
    typeof source.json_schema === 'object' &&
    !Array.isArray(source.json_schema)
  ) {
    serialized.json_schema = source.json_schema;
  }
  return serialized;
}
