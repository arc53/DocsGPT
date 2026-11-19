import { describe, expect, it } from 'vitest';

import type { CredentialField } from './types';
import { urlParametersValid, withUrlParameters } from './urlParameters';

const projectRef: CredentialField = {
  key: 'project_ref',
  label: 'Project ref',
  secret: false,
  required: true,
  pattern: '[a-z]{20}',
};
const REF = 'abcdefghijklmnopqrst';

describe('urlParametersValid', () => {
  it('accepts a value its pattern matches whole', () => {
    expect(urlParametersValid([projectRef], { project_ref: REF })).toBe(true);
    expect(urlParametersValid([projectRef], { project_ref: ` ${REF} ` })).toBe(
      true,
    );
  });

  it.each([
    ['missing', {}],
    ['empty', { project_ref: '' }],
    ['uppercase', { project_ref: REF.toUpperCase() }],
    ['too long', { project_ref: `${REF}u` }],
    ['a prefix only', { project_ref: `${REF}&read_only=true` }],
  ])('refuses a value that is %s', (_name, values) => {
    expect(urlParametersValid([projectRef], values)).toBe(false);
  });

  it('has nothing to check for a preset without parameters', () => {
    expect(urlParametersValid([], {})).toBe(true);
  });
});

describe('withUrlParameters', () => {
  it('adds each value to the preset URL', () => {
    expect(
      withUrlParameters('https://mcp.supabase.com/mcp', [projectRef], {
        project_ref: ` ${REF} `,
      }),
    ).toBe(`https://mcp.supabase.com/mcp?project_ref=${REF}`);
  });

  it('leaves a preset without parameters on its URL', () => {
    expect(withUrlParameters('https://mcp.notion.com/mcp', [], {})).toBe(
      'https://mcp.notion.com/mcp',
    );
  });
});
