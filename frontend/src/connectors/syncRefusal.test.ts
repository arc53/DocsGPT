import type { TFunction } from 'i18next';
import { describe, expect, it } from 'vitest';

import { syncRefusal } from './syncRefusal';

const t = ((key: string) => key) as unknown as TFunction;
const key = (name: string) => `settings.connectors.detail.${name}`;

describe('syncRefusal', () => {
  it.each([
    ['wiki', 'syncRefusedWiki'],
    ['not_syncable', 'syncRefusedNotSyncable'],
    ['connector_source', 'syncRefusedConnector'],
    ['invalid_source', 'syncRefusedInvalid'],
    ['reconnect_needed', 'syncRefusedReconnect'],
    ['connection_missing', 'syncRefusedConnectionMissing'],
  ])('words the %s code', (code, name) => {
    expect(syncRefusal(t, { code, error: 'English' }, { status: 400 })).toBe(
      key(name),
    );
  });

  it.each([{ error: 'Source not found' }, { message: 'Source not found' }])(
    'words a deleted source (a 404 with no code, %o)',
    (body) => {
      expect(syncRefusal(t, body, { status: 404 })).toBe(
        key('syncRefusedInvalid'),
      );
    },
  );

  it("shows the server's error, else its message, for another refusal", () => {
    expect(syncRefusal(t, { error: 'Paused', message: 'x' })).toBe('Paused');
    expect(syncRefusal(t, { error: '', message: 'Nothing to sync.' })).toBe(
      'Nothing to sync.',
    );
  });

  it('words a 403 as forbidden only for a caller that opts in', () => {
    const body = { code: 'wiki', error: 'Forbidden' };
    expect(syncRefusal(t, body, { status: 403, forbidden: true })).toBe(
      'settings.sources.errors.forbidden',
    );
    expect(syncRefusal(t, body, { status: 403 })).toBe(key('syncRefusedWiki'));
    expect(syncRefusal(t, body, { status: 400, forbidden: true })).toBe(
      key('syncRefusedWiki'),
    );
  });

  it('falls back to the generic line', () => {
    expect(syncRefusal(t, null)).toBe(key('syncFailed'));
    expect(syncRefusal(t, { success: false }, { fallback: 'generic' })).toBe(
      'generic',
    );
    // A server error's text (a traceback) is never shown.
    expect(
      syncRefusal(t, { error: 'Traceback' }, { status: 500, fallback: 'g' }),
    ).toBe('g');
  });
});
