import { describe, expect, it } from 'vitest';

import {
  IngestorDefaultConfigs,
  IngestorFormSchemas,
  getIngestorSchema,
  UPLOAD_AND_WEB_INGESTORS,
} from './ingestor';

describe('wiki ingestor schema', () => {
  it('registers a "wiki" ingestor with the New wiki label', () => {
    const schema = getIngestorSchema('wiki');
    expect(schema).toBeDefined();
    expect(schema?.label).toBe('New wiki');
  });

  it('exposes an optional initial_content textarea field', () => {
    const schema = getIngestorSchema('wiki');
    const field = schema?.fields.find((f) => f.name === 'initial_content');
    expect(field).toBeDefined();
    expect(field?.type).toBe('textarea');
    expect(field?.required ?? false).toBe(false);
  });

  it('does not require a remote file picker (create-only, no ingest)', () => {
    const schema = getIngestorSchema('wiki');
    const pickerTypes = (schema?.fields ?? []).map((f) => f.type);
    expect(pickerTypes).not.toContain('local_file_picker');
    expect(pickerTypes).not.toContain('remote_file_picker');
  });

  it('provides a default config for the wiki type', () => {
    expect(IngestorDefaultConfigs.wiki).toEqual({
      name: '',
      config: { initial_content: '' },
    });
  });

  it('keeps the wiki schema discoverable in the form schema list', () => {
    expect(IngestorFormSchemas.some((s) => s.key === 'wiki')).toBe(true);
  });
});

describe('Add knowledge tiles', () => {
  // GitHub sits with the services ("From a service"), not among these.
  it('lists the no-account types, without GitHub', () => {
    expect(UPLOAD_AND_WEB_INGESTORS).toEqual([
      'local_file',
      'url',
      'crawler',
      'wiki',
    ]);
  });

  it('gives every tile a lucide icon', () => {
    for (const key of UPLOAD_AND_WEB_INGESTORS) {
      const icon = getIngestorSchema(key)?.icon;
      // lucide-react icons are forwardRef components.
      expect(typeof icon === 'object' || typeof icon === 'function').toBe(true);
    }
  });
});
