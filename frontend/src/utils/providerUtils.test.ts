const claim = vi.fn();
vi.mock('../api/services/connectorsService', () => ({
  default: { claim: (...args: unknown[]) => claim(...args) },
}));

import { claimLegacySessionTokens } from './providerUtils';

describe('claimLegacySessionTokens', () => {
  beforeEach(() => {
    claim.mockReset();
    localStorage.clear();
  });

  it('claims every stored session token once and removes it', async () => {
    localStorage.setItem('google_drive_session_token', 'g-token');
    localStorage.setItem('confluence_session_token', 'c-token');
    claim.mockResolvedValue({ success: true, connection_id: 'x' });

    await claimLegacySessionTokens('jwt');

    expect(claim).toHaveBeenCalledWith('google_drive', 'g-token', 'jwt');
    expect(claim).toHaveBeenCalledWith('confluence', 'c-token', 'jwt');
    expect(claim).toHaveBeenCalledTimes(2);
    expect(localStorage.getItem('google_drive_session_token')).toBeNull();
    expect(localStorage.getItem('confluence_session_token')).toBeNull();
  });

  it('drops the token even when the claim fails', async () => {
    localStorage.setItem('share_point_session_token', 's-token');
    claim.mockRejectedValue(new Error('offline'));
    await claimLegacySessionTokens(null);
    expect(localStorage.getItem('share_point_session_token')).toBeNull();
  });

  it('does nothing without stored tokens', async () => {
    await claimLegacySessionTokens(null);
    expect(claim).not.toHaveBeenCalled();
  });
});
