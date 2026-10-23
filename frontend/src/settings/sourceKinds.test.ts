import { describe, expect, it } from 'vitest';

import type { Doc } from '../models/misc';
import { canSyncSource } from './sourceKinds';

const doc = (fields: Partial<Doc> = {}): Doc => ({
  id: 'src-1',
  name: 'Contracts',
  date: '',
  model: '',
  ...fields,
});

describe('canSyncSource', () => {
  it('syncs a connector source from its connection', () => {
    expect(
      canSyncSource(
        doc({ type: 'connector:file', connectionId: 'c-1', access: 'owner' }),
      ),
    ).toBe(true);
  });

  // The server refuses it (connection_missing): the account was removed.
  it("doesn't sync the owner's connector source whose connection is gone", () => {
    expect(
      canSyncSource(
        doc({ type: 'connector:file', connectionId: null, access: 'owner' }),
      ),
    ).toBe(false);
  });

  // A team editor's sync runs with the owner's first connection for the
  // provider, which the editor can't see; the server decides.
  it("leaves an editor's Sync now to the server", () => {
    expect(
      canSyncSource(
        doc({ type: 'connector:file', connectionId: null, access: 'editor' }),
      ),
    ).toBe(true);
  });

  it('keeps Sync now when the list says nothing of the connection', () => {
    expect(
      canSyncSource(doc({ type: 'connector:file', access: 'owner' })),
    ).toBe(true);
  });

  it('syncs a scheduled source with no connection, never a wiki', () => {
    expect(canSyncSource(doc({ type: 'url', syncFrequency: 'never' }))).toBe(
      true,
    );
    expect(canSyncSource(doc({ type: 'wiki', connectionId: 'c-1' }))).toBe(
      false,
    );
  });
});
