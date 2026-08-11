import { describe, expect, it } from 'vitest';

import { extractToolError } from './SchedulerToolCallCard';

// Regression for the iter-6 issue where ``cancel_scheduled_task`` returning
// a plain ``"Error: …"`` string still rendered "Scheduled task cancelled."
// The fix is to extract the error message so the card can branch on it.
describe('extractToolError', () => {
  it('returns the message for an Error: prefixed string', () => {
    expect(
      extractToolError('Error: scheduled task not found or already terminal.'),
    ).toBe('scheduled task not found or already terminal.');
  });

  it('trims leading whitespace before the prefix', () => {
    expect(extractToolError('  Error: foo  ')).toBe('foo');
  });

  it('returns null for JSON success payloads', () => {
    expect(
      extractToolError(JSON.stringify({ task_id: 'x', status: 'cancelled' })),
    ).toBeNull();
  });

  it('returns null for plain non-error strings', () => {
    expect(extractToolError('done')).toBeNull();
  });

  it('returns null for object results', () => {
    expect(extractToolError({ task_id: 'x' })).toBeNull();
  });

  it('returns null for undefined / null', () => {
    expect(extractToolError(undefined)).toBeNull();
    expect(extractToolError(null)).toBeNull();
  });
});
