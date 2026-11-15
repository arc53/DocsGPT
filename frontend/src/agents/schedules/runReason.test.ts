import { describe, expect, it } from 'vitest';

import { OWNER_INACTIVE, runReason } from './runReason';

describe('runReason', () => {
  it('is the error type when the run has one', () => {
    expect(
      runReason({ status: 'failed', error: 'boom', error_type: 'timeout' }),
    ).toBe('timeout');
  });

  it("names a run skipped while the owner's account is deactivated", () => {
    expect(
      runReason({ status: 'skipped', error: OWNER_INACTIVE, error_type: null }),
    ).toBe(OWNER_INACTIVE);
  });

  it('is null for a run with no reason', () => {
    expect(
      runReason({ status: 'success', error: null, error_type: null }),
    ).toBeNull();
  });
});
