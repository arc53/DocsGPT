import { describe, expect, it } from 'vitest';

import { isPauseSkip, OWNER_INACTIVE, runReason } from './runReason';

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

  it.each(['payer_out_of_allowance', 'payer_left', 'no_payer'] as const)(
    'names a run skipped while paused for %s',
    (reason) => {
      expect(
        runReason({ status: 'skipped', error: reason, error_type: reason }),
      ).toBe(reason);
      // A row written before the error type existed still reads.
      expect(
        runReason({ status: 'skipped', error: reason, error_type: null }),
      ).toBe(reason);
    },
  );

  it('names a run stopped mid-way at its payer’s allowance', () => {
    expect(
      runReason({
        status: 'failed',
        error: 'quota exceeded',
        error_type: 'payer_out_of_allowance',
      }),
    ).toBe('payer_out_of_allowance');
  });

  it('does not read an unknown skipped error as a reason', () => {
    expect(
      runReason({ status: 'skipped', error: 'something', error_type: null }),
    ).toBeNull();
  });
});

describe('isPauseSkip', () => {
  it('is true for a run skipped while paused for its payer', () => {
    expect(
      isPauseSkip({
        status: 'skipped',
        error: 'payer_left',
        error_type: 'payer_left',
      }),
    ).toBe(true);
    expect(
      isPauseSkip({
        status: 'skipped',
        error: OWNER_INACTIVE,
        error_type: null,
      }),
    ).toBe(true);
  });

  it('is false for a failure, even one at the payer’s allowance', () => {
    expect(
      isPauseSkip({
        status: 'failed',
        error: 'quota exceeded',
        error_type: 'payer_out_of_allowance',
      }),
    ).toBe(false);
    expect(
      isPauseSkip({ status: 'skipped', error: null, error_type: 'overlap' }),
    ).toBe(false);
  });
});
