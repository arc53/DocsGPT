import { describe, expect, it, vi } from 'vitest';

import {
  buildWikiNavigator,
  findWikiPage,
  provenanceKey,
  saveWikiPage,
  wikiLinkTarget,
  wikiPageLabel,
} from './wikiViewerUtils';
import { filterNavigatorLeaves } from './tree/navigatorUtils';

const jsonResponse = (status: number, body: unknown): Response =>
  ({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  }) as unknown as Response;

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

describe('wikiPageLabel', () => {
  it('prefers the stored title', () => {
    expect(wikiPageLabel({ path: '/a/b.md', title: 'Hello' })).toBe('Hello');
  });

  it('turns a file name into sentence case', () => {
    expect(
      wikiPageLabel({ path: '/company/meeting-and-decision-norms.md' }),
    ).toBe('Meeting and decision norms');
    expect(wikiPageLabel({ path: '/people/leave_and_hours.md' })).toBe(
      'Leave and hours',
    );
  });

  it('calls the root index Home', () => {
    expect(wikiPageLabel({ path: '/index.md' })).toBe('Home');
    expect(wikiPageLabel({ path: '/sales/index.md' })).toBe('Index');
  });
});

describe('buildWikiNavigator', () => {
  it('puts root pages first (Home leading), then one group per top folder', () => {
    const nodes = buildWikiNavigator([
      { path: '/people/onboarding.md' },
      { path: '/company/mission.md' },
      { path: '/arc53.md' },
      { path: '/index.md' },
      { path: '/company/org/model.md' },
    ]);
    expect(nodes.map((n) => [n.kind, n.label])).toEqual([
      ['leaf', 'Home'],
      ['leaf', 'Arc53'],
      ['folder', 'company'],
      ['folder', 'people'],
    ]);
    expect(nodes[2].children!.map((n) => n.id)).toEqual([
      '/company/mission.md',
      '/company/org/model.md',
    ]);
    expect(nodes[2].count).toBe(2);
  });

  // A filter match's second line is the page's own folder, not only the top
  // folder its group is named after.
  it('gives each filter match its full parent path', () => {
    const nodes = buildWikiNavigator([
      { path: '/index.md' },
      { path: '/contracts/europe/2026/hamburg-port-dues.md' },
      { path: '/playbooks/hamburg-strike-plan.md' },
    ]);
    expect(
      filterNavigatorLeaves(nodes, 'hamburg').map((m) => m.parentPath),
    ).toEqual(['/contracts/europe/2026', '/playbooks']);
    expect(filterNavigatorLeaves(nodes, 'index')[0].parentPath).toBe('');
  });
});

describe('wikiLinkTarget', () => {
  it.each([
    [
      '/engineering/incident-response.md',
      '/index.md',
      'engineering/incident-response.md',
    ],
    [
      'data-classification.md',
      '/security/overview.md',
      'security/data-classification.md',
    ],
    [
      './data-classification.md',
      'security/overview.md',
      'security/data-classification.md',
    ],
    ['../people/leave.md', '/engineering/runbook.md', 'people/leave.md'],
    ['/a/b.md#section', '/index.md', 'a/b.md'],
    ['/Leave%20policy.md', '/index.md', 'Leave policy.md'],
  ])('resolves %s from %s', (href, from, expected) => {
    expect(wikiLinkTarget(href, from)).toBe(expected);
  });

  it.each(['https://www.arc53.com/', 'mailto:a@b.c', '#top', '//cdn.x/y', ''])(
    'leaves %s to the browser',
    (href) => {
      expect(wikiLinkTarget(href, '/index.md')).toBeNull();
    },
  );
});

describe('findWikiPage', () => {
  const pages = [
    { path: '/index.md', title: null, token_count: 1 },
    { path: '/people/leave.md', title: null, token_count: 1 },
  ];

  it('matches with or without the leading slash, and without .md', () => {
    expect(findWikiPage(pages, 'people/leave.md')?.path).toBe(
      '/people/leave.md',
    );
    expect(findWikiPage(pages, '/people/leave.md')?.path).toBe(
      '/people/leave.md',
    );
    expect(findWikiPage(pages, 'people/leave')?.path).toBe('/people/leave.md');
  });

  it('finds nothing for a page that does not exist', () => {
    expect(findWikiPage(pages, 'people/gone.md')).toBeUndefined();
  });
});
