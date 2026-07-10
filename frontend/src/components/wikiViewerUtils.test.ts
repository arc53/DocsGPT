import { describe, expect, it, vi } from 'vitest';

import {
  formatRelativeTime,
  provenanceKey,
  saveWikiPage,
} from './wikiViewerUtils';

const jsonResponse = (status: number, body: unknown): Response =>
  ({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  }) as unknown as Response;

describe('formatRelativeTime', () => {
  const now = Date.parse('2026-06-22T12:00:00Z');

  it('returns null for empty or invalid values', () => {
    expect(formatRelativeTime(null, now)).toBeNull();
    expect(formatRelativeTime(undefined, now)).toBeNull();
    expect(formatRelativeTime('not-a-date', now)).toBeNull();
  });

  it('formats a recent edit in minutes', () => {
    const fiveMinAgo = new Date(now - 5 * 60000).toISOString();
    expect(formatRelativeTime(fiveMinAgo, now)).toBe('5 minutes ago');
  });

  it('formats an older edit in days', () => {
    const threeDaysAgo = new Date(now - 3 * 86400000).toISOString();
    expect(formatRelativeTime(threeDaysAgo, now)).toBe('3 days ago');
  });
});

describe('provenanceKey', () => {
  it('maps the current user to "you"', () => {
    expect(provenanceKey('human', 'user-1', 'user-1')).toBe('you');
  });

  it('maps agent and human writes', () => {
    expect(provenanceKey('agent', 'someone', 'user-1')).toBe('agent');
    expect(provenanceKey('human', 'someone', 'user-1')).toBe('human');
  });

  it('falls back to "unknown" for missing provenance', () => {
    expect(provenanceKey(null, null, null)).toBe('unknown');
    expect(provenanceKey('weird', 'someone', 'user-1')).toBe('unknown');
  });
});

describe('saveWikiPage', () => {
  it('sends expected_version and returns the saved page', async () => {
    const updateWikiPage = vi
      .fn()
      .mockResolvedValue(
        jsonResponse(200, { page: { path: '/a.md', version: 3 } }),
      );
    const getWikiPage = vi.fn();
    const service = { updateWikiPage, getWikiPage };

    const outcome = await saveWikiPage(
      service,
      'src-1',
      '/a.md',
      'new body',
      2,
      'tok',
    );

    expect(updateWikiPage).toHaveBeenCalledWith(
      'src-1',
      { path: '/a.md', content: 'new body', expected_version: 2 },
      'tok',
    );
    expect(getWikiPage).not.toHaveBeenCalled();
    expect(outcome).toEqual({
      status: 'saved',
      page: { path: '/a.md', version: 3 },
    });
  });

  it('reloads the latest page on a 409 conflict', async () => {
    const updateWikiPage = vi.fn().mockResolvedValue(jsonResponse(409, {}));
    const getWikiPage = vi.fn().mockResolvedValue(
      jsonResponse(200, {
        page: { path: '/a.md', version: 5, content: 'their edit' },
      }),
    );
    const service = { updateWikiPage, getWikiPage };

    const outcome = await saveWikiPage(
      service,
      'src-1',
      '/a.md',
      'my edit',
      2,
      'tok',
    );

    expect(getWikiPage).toHaveBeenCalledWith('src-1', '/a.md', 'tok');
    expect(outcome).toEqual({
      status: 'conflict',
      page: { path: '/a.md', version: 5, content: 'their edit' },
    });
  });

  it('reports forbidden on 403 without reloading', async () => {
    const updateWikiPage = vi.fn().mockResolvedValue(jsonResponse(403, {}));
    const getWikiPage = vi.fn();
    const service = { updateWikiPage, getWikiPage };

    const outcome = await saveWikiPage(
      service,
      'src-1',
      '/a.md',
      'x',
      1,
      'tok',
    );

    expect(getWikiPage).not.toHaveBeenCalled();
    expect(outcome).toEqual({ status: 'forbidden' });
  });

  it('reports a generic error on other failures', async () => {
    const updateWikiPage = vi.fn().mockResolvedValue(jsonResponse(400, {}));
    const getWikiPage = vi.fn();
    const service = { updateWikiPage, getWikiPage };

    const outcome = await saveWikiPage(
      service,
      'src-1',
      '/a.md',
      'x',
      1,
      'tok',
    );

    expect(outcome).toEqual({ status: 'error' });
  });
});
