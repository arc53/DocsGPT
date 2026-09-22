import { describe, expect, it } from 'vitest';

import { categoryTone, eventLabel, eventTone, outcomeTone } from './AdminUI';

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
    expect(eventTone('oidc_login_denied')).toBe('danger');
    expect(eventTone('agent.deleted')).toBe('danger');
  });

  it('flags revocations as a warning, not a failure', () => {
    expect(eventTone('role_revoked')).toBe('warning');
    expect(eventTone('agent.key_regenerated')).toBe('warning');
  });

  it('marks an admin grant with the brand tone', () => {
    expect(eventTone('role_granted')).toBe('brand');
  });

  it('leaves routine events muted', () => {
    expect(eventTone('oidc_login')).toBe('muted');
    expect(eventTone('anything_else')).toBe('muted');
  });
});

describe('categoryTone', () => {
  it('has a tone for every category the API declares', () => {
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
    expect(categoryTone('invented')).toBe('muted');
  });
});

describe('outcomeTone', () => {
  it('reads a block or a denial as dangerous', () => {
    expect(outcomeTone('blocked')).toBe('danger');
    expect(outcomeTone('denied')).toBe('danger');
  });

  it('reads an allowed command as a success', () => {
    expect(outcomeTone('allowed')).toBe('success');
  });

  it('leaves an unfamiliar outcome muted', () => {
    expect(outcomeTone('pending')).toBe('muted');
  });
});
