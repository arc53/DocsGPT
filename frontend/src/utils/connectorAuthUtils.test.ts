import { describe, expect, it } from 'vitest';

import { isTrustedConnectorMessage } from './connectorAuthUtils';

const popup = {} as Window;
const otherWindow = {} as Window;

describe('isTrustedConnectorMessage', () => {
  it('rejects messages when no auth popup is open', () => {
    expect(
      isTrustedConnectorMessage(
        { source: popup, origin: 'https://api.example.com' },
        null,
        'https://api.example.com',
      ),
    ).toBe(false);
  });

  it('rejects messages that do not come from the auth popup', () => {
    expect(
      isTrustedConnectorMessage(
        { source: otherWindow, origin: 'https://api.example.com' },
        popup,
        'https://api.example.com',
      ),
    ).toBe(false);
  });

  it('rejects messages from the popup when its origin is unexpected', () => {
    expect(
      isTrustedConnectorMessage(
        { source: popup, origin: 'https://evil.example.com' },
        popup,
        'https://api.example.com',
      ),
    ).toBe(false);
  });

  it('accepts messages from the popup on the callback origin', () => {
    expect(
      isTrustedConnectorMessage(
        { source: popup, origin: 'https://api.example.com' },
        popup,
        'https://api.example.com',
      ),
    ).toBe(true);
  });

  it('falls back to the popup identity check when no origin is known', () => {
    expect(
      isTrustedConnectorMessage(
        { source: popup, origin: 'https://api.example.com' },
        popup,
        null,
      ),
    ).toBe(true);
  });
});
