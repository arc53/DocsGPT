import { describe, expect, it } from 'vitest';

import { buildSimpleCel, parseSimpleCel } from './simpleCel';

describe('parseSimpleCel', () => {
  it('parses a plain variable comparison', () => {
    expect(parseSimpleCel('status == "open"')).toEqual({
      variable: 'status',
      operator: '==',
      value: 'open',
    });
  });

  it('parses a dotted variable path the backend CEL accepts', () => {
    // Regression: Simple mode blocked `audit.high_risk_accounts >= 3` at
    // Preview ("must specify a variable") while createWorkflow accepted it.
    expect(parseSimpleCel('audit.high_risk_accounts >= 3')).toEqual({
      variable: 'audit.high_risk_accounts',
      operator: '>=',
      value: '3',
    });
  });

  it('parses dotted paths with contains/startsWith', () => {
    expect(parseSimpleCel('audit.summary.contains("risk")')).toEqual({
      variable: 'audit.summary',
      operator: 'contains',
      value: 'risk',
    });
    expect(parseSimpleCel('doc.name.startsWith("Q3")')).toEqual({
      variable: 'doc.name',
      operator: 'startsWith',
      value: 'Q3',
    });
  });

  it('parses quoted comparisons on dotted paths', () => {
    expect(parseSimpleCel('meta.region == "EMEA"')).toEqual({
      variable: 'meta.region',
      operator: '==',
      value: 'EMEA',
    });
  });

  it('keeps variable-less forms working', () => {
    expect(parseSimpleCel('>= 4')).toEqual({
      variable: '',
      operator: '>=',
      value: '4',
    });
    expect(parseSimpleCel('contains("x")')).toEqual({
      variable: '',
      operator: 'contains',
      value: 'x',
    });
  });

  it('falls back to an empty template for unparseable input', () => {
    expect(parseSimpleCel('!!not cel!!')).toEqual({
      variable: '',
      operator: '==',
      value: '',
    });
  });
});

describe('buildSimpleCel round-trip', () => {
  it('round-trips a dotted numeric comparison', () => {
    const built = buildSimpleCel('audit.high_risk_accounts', '>=', '3');
    expect(built).toBe('audit.high_risk_accounts >= 3');
    expect(parseSimpleCel(built)).toEqual({
      variable: 'audit.high_risk_accounts',
      operator: '>=',
      value: '3',
    });
  });

  it('round-trips a dotted contains', () => {
    const built = buildSimpleCel('audit.summary', 'contains', 'risk');
    expect(parseSimpleCel(built)).toEqual({
      variable: 'audit.summary',
      operator: 'contains',
      value: 'risk',
    });
  });
});
