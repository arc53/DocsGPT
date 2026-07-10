import { describe, expect, it } from 'vitest';

import {
  createDefaultCodeConfig,
  normalizeCodeConfig,
  parseCodeInputs,
  parseCodeJsonSchemaDraft,
  serializeCodeConfig,
  stringifyCodeInputs,
  validateCodeJsonSchema,
} from './codeNodeConfig';

describe('validateCodeJsonSchema', () => {
  it('treats undefined/null as valid (no schema)', () => {
    expect(validateCodeJsonSchema(undefined)).toBeNull();
    expect(validateCodeJsonSchema(null)).toBeNull();
  });

  it('rejects arrays and non-objects', () => {
    expect(validateCodeJsonSchema([])).toMatch(/valid JSON object/);
    expect(validateCodeJsonSchema('x')).toMatch(/valid JSON object/);
  });

  it('requires a type or schema field', () => {
    expect(validateCodeJsonSchema({})).toMatch(/"type" or "schema"/);
    expect(validateCodeJsonSchema({ type: 'object' })).toBeNull();
    expect(validateCodeJsonSchema({ schema: {} })).toBeNull();
  });
});

describe('parseCodeJsonSchemaDraft', () => {
  it('returns undefined schema and no error for blank input', () => {
    expect(parseCodeJsonSchemaDraft('   ')).toEqual({
      schema: undefined,
      error: null,
    });
  });

  it('flags invalid JSON', () => {
    const result = parseCodeJsonSchemaDraft('{ not json');
    expect(result.schema).toBeUndefined();
    expect(result.error).toMatch(/valid JSON/);
  });

  it('flags structurally invalid schema', () => {
    const result = parseCodeJsonSchemaDraft('{"foo": 1}');
    expect(result.schema).toBeUndefined();
    expect(result.error).toMatch(/"type" or "schema"/);
  });

  it('parses a valid schema', () => {
    const result = parseCodeJsonSchemaDraft(
      '{"type":"object","properties":{}}',
    );
    expect(result.error).toBeNull();
    expect(result.schema).toEqual({ type: 'object', properties: {} });
  });
});

describe('inputs (de)serialization', () => {
  it('splits on newlines and commas and trims', () => {
    expect(parseCodeInputs('A1\nfoo, bar\n\n  baz  ')).toEqual([
      'A1',
      'foo',
      'bar',
      'baz',
    ]);
  });

  it('round-trips through stringify', () => {
    const inputs = ['A1', 'state_var'];
    expect(parseCodeInputs(stringifyCodeInputs(inputs))).toEqual(inputs);
  });

  it('stringifies undefined to empty string', () => {
    expect(stringifyCodeInputs(undefined)).toBe('');
  });
});

describe('createDefaultCodeConfig', () => {
  it('returns python defaults with empty code and inputs', () => {
    expect(createDefaultCodeConfig()).toEqual({
      code: '',
      inputs: [],
    });
  });
});

describe('serializeCodeConfig', () => {
  it('omits optional fields when empty', () => {
    const serialized = serializeCodeConfig({
      code: 'print(1)',
      inputs: ['', '  '],
      output_variable: '   ',
    });
    expect(serialized).toEqual({
      code: 'print(1)',
      inputs: [],
    });
    expect('output_variable' in serialized).toBe(false);
    expect('timeout' in serialized).toBe(false);
    expect('json_schema' in serialized).toBe(false);
  });

  it('keeps all CodeNodeConfig fields when present', () => {
    const serialized = serializeCodeConfig({
      code: 'print(1)',
      inputs: ['A1', 'state_var'],
      output_variable: 'result',
      timeout: 30,
      json_schema: { type: 'object' },
    });
    expect(serialized).toEqual({
      code: 'print(1)',
      inputs: ['A1', 'state_var'],
      output_variable: 'result',
      timeout: 30,
      json_schema: { type: 'object' },
    });
  });

  it('falls back to python defaults for an undefined config', () => {
    expect(serializeCodeConfig(undefined)).toEqual({
      code: '',
      inputs: [],
    });
  });
});

describe('normalizeCodeConfig', () => {
  it('tolerates a missing/empty payload', () => {
    expect(normalizeCodeConfig(undefined)).toEqual({
      code: '',
      inputs: [],
    });
  });

  it('coerces bad field types without throwing', () => {
    const config = normalizeCodeConfig({
      code: 42,
      inputs: ['A1', 5, 'B2'],
      output_variable: '',
      timeout: 'soon',
      json_schema: [],
    } as unknown as Record<string, unknown>);
    expect(config).toEqual({
      code: '',
      inputs: ['A1', 'B2'],
    });
  });

  it('preserves a fully populated saved config (round-trip with serialize)', () => {
    const saved = {
      code: 'print(1)',
      inputs: ['A1'],
      output_variable: 'result',
      timeout: 30,
      json_schema: { type: 'object' },
    };
    const normalized = normalizeCodeConfig(saved);
    expect(serializeCodeConfig(normalized)).toEqual(saved);
  });
});
