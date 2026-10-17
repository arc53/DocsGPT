import { describe, expect, it } from 'vitest';

import {
  categoryTone,
  eventLabel,
  eventTone,
  outcomeLabel,
  outcomeTone,
} from './AdminUI';

describe('eventLabel', () => {
  it('humanizes the events it knows', () => {
    expect(eventLabel('oidc_login_denied')).toBe('Login denied');
    expect(eventLabel('source.deleted')).toBe('Source deleted');
    expect(eventLabel('device.run_command')).toBe('Device command');
  });

  it('stays legible for an event a newer release added', () => {
    expect(eventLabel('source.archived')).toBe('Source archived');
    expect(eventLabel('brand_new_event')).toBe('Brand new event');
  });
});

describe('eventTone', () => {
  it('flags removals and refusals', () => {
    expect(eventTone('oidc_login_denied')).toBe('destructive');
    expect(eventTone('agent.deleted')).toBe('destructive');
  });

  it('flags revocations as a warning, not a failure', () => {
    expect(eventTone('role_revoked')).toBe('warning');
    expect(eventTone('agent.key_regenerated')).toBe('warning');
  });

  it('marks an admin grant with the brand (default) variant', () => {
    expect(eventTone('role_granted')).toBe('default');
  });

  it('leaves routine events muted', () => {
    expect(eventTone('oidc_login')).toBe('neutral');
    expect(eventTone('anything_else')).toBe('neutral');
  });
});

describe('categoryTone', () => {
  it('has a variant for every category the API declares', () => {
    expect(categoryTone('identity')).toBe('outline');
    expect(categoryTone('access')).toBe('default');
    expect(categoryTone('safety')).toBe('destructive');
    expect(categoryTone('other')).toBe('neutral');
    for (const category of [
      'identity',
      'access',
      'config',
      'data',
      'device',
      'safety',
      'other',
    ]) {
      expect(categoryTone(category)).toBeTruthy();
    }
  });

  it('falls back for an unknown category', () => {
    expect(categoryTone('invented')).toBe('neutral');
  });
});

describe('outcomeTone', () => {
  // The values below are the only ones the writers produce: guardrails emit
  // triggered/not_evaluated, the device feed emits dispatched.
  it('flags a guardrail that fired', () => {
    expect(outcomeTone('triggered')).toBe('destructive');
  });

  it('leaves a check that never ran neutral', () => {
    expect(outcomeTone('not_evaluated')).toBe('neutral');
  });

  it('reads a dispatched device command as a success', () => {
    expect(outcomeTone('dispatched')).toBe('success');
  });

  it('leaves an unfamiliar outcome muted', () => {
    expect(outcomeTone('something-new')).toBe('neutral');
  });
});

describe('outcomeLabel', () => {
  it('humanizes the values the journals write', () => {
    expect(outcomeLabel('not_evaluated')).toBe('Not evaluated');
    expect(outcomeLabel('dispatched')).toBe('Dispatched');
  });

  it('stays legible for an unknown value', () => {
    expect(outcomeLabel('rate_limited')).toBe('Rate limited');
  });
});
