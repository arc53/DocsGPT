import type { MultiSelectPopoverItem } from '../components/MultiSelectPopover';
import {
  confirmTakeOver,
  NO_AUDIENCE,
  readSponsorRefusal,
  saveWithSponsorConsent,
  withAttachedOptions,
  withAttachedToolRows,
} from './sponsorConsent';

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

describe('readSponsorRefusal', () => {
  const resources = [{ key: 'tool:t1', type: 'tool', id: 't1', name: 'Jira' }];
  const audience = {
    teams: ['Support'],
    api_key: true,
    public_link: false,
    webhook: false,
  };

  it('reads a confirmation request and leaves the body readable', async () => {
    const response = json(409, {
      success: false,
      code: 'sponsor_confirmation_required',
      message: 'm',
      resources,
      audience,
    });
    expect(await readSponsorRefusal(response)).toEqual({
      kind: 'confirm',
      confirmation: { resources, audience },
    });
    expect((await response.json()).message).toBe('m');
  });

  it('reads a refusal the caller may not sponsor', async () => {
    const response = json(403, {
      code: 'sponsor_not_allowed',
      message: 'no',
      resources,
    });
    expect(await readSponsorRefusal(response)).toEqual({
      kind: 'notAllowed',
      resources,
    });
  });

  it('ignores other failures', async () => {
    expect(
      await readSponsorRefusal(json(409, { code: 'stale_write' })),
    ).toBeNull();
    expect(await readSponsorRefusal(json(403, { message: 'x' }))).toBeNull();
    expect(
      await readSponsorRefusal(new Response('<html>', { status: 502 })),
    ).toBeNull();
  });
});

describe('withAttachedToolRows', () => {
  const labels = { group: 'On this agent', description: 'Remove only' };
  const listed: MultiSelectPopoverItem[] = [
    { id: 'mine', label: 'My tool', group: 'Custom' },
  ];

  it('adds a removable row for an attached tool the caller cannot list', () => {
    const items = withAttachedToolRows(
      listed,
      [
        { id: 'mine', name: 'api_tool', display_name: 'My tool' },
        { id: 'owners', name: 'jira', display_name: 'Owner Jira' },
      ],
      labels,
    );
    expect(items.map((item) => item.id)).toEqual(['mine', 'owners']);
    const locked = items[1];
    expect(locked.label).toBe('Owner Jira');
    expect(locked.group).toBe('On this agent');
    expect(locked.description).toBe('Remove only');
    expect(locked.disabled).toBeFalsy();
  });

  it('keeps one row per tool when it is listed or repeated', () => {
    const tool = { id: 'owners', name: 'jira', display_name: 'Owner Jira' };
    const items = withAttachedToolRows(listed, [tool, tool], labels);
    expect(items.map((item) => item.id)).toEqual(['mine', 'owners']);
  });
});

describe('readSponsorRefusal: stale confirmations', () => {
  it('reads a confirmation that names something the save no longer needs', async () => {
    const response = json(400, {
      code: 'sponsor_confirmation_unexpected',
      unexpected: ['tool:gone'],
    });
    expect(await readSponsorRefusal(response)).toEqual({ kind: 'unexpected' });
  });

  it('ignores an ordinary 400', async () => {
    expect(await readSponsorRefusal(json(400, { message: 'bad' }))).toBeNull();
  });
});

describe('saveWithSponsorConsent', () => {
  const confirmation = {
    resources: [
      { key: 'tool:t1', type: 'tool' as const, id: 't1', name: 'Jira' },
    ],
    audience: { teams: [], api_key: false, public_link: false, webhook: false },
  };
  const refused = () =>
    json(409, {
      code: 'sponsor_confirmation_required',
      ...confirmation,
    });

  it('sends once when nothing needs confirming', async () => {
    const send = vi.fn(async () => json(200, { success: true }));
    const ask = vi.fn();
    const response = await saveWithSponsorConsent(send, ask, ['tool:x']);
    expect(response?.status).toBe(200);
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith(['tool:x']);
    expect(ask).not.toHaveBeenCalled();
  });

  it('asks, then resends with the agreed keys and any it already had', async () => {
    const send = vi
      .fn<(keys: string[]) => Promise<Response>>()
      .mockResolvedValueOnce(refused())
      .mockResolvedValueOnce(json(200, { success: true }));
    const ask = vi.fn(async () => ['tool:t1']);
    const response = await saveWithSponsorConsent(send, ask, ['source:s1']);
    expect(ask).toHaveBeenCalledWith(confirmation);
    expect(send.mock.calls.map(([keys]) => keys)).toEqual([
      ['source:s1'],
      ['source:s1', 'tool:t1'],
    ]);
    expect(response?.status).toBe(200);
  });

  it('returns null when the caller declines, without resending', async () => {
    const send = vi.fn(async () => refused());
    const response = await saveWithSponsorConsent(send, async () => null);
    expect(response).toBeNull();
    expect(send).toHaveBeenCalledTimes(1);
  });

  // A workflow save answers in the workflow routes' shape; the round trip
  // is the same.
  it('passes other failures straight back', async () => {
    const failure = json(400, { success: false, error: 'Workflow invalid' });
    const send = vi.fn(async () => failure);
    expect(await saveWithSponsorConsent(send, vi.fn())).toBe(failure);
  });
});

describe('withAttachedOptions', () => {
  it('adds a labelled option for a selected id the caller cannot list', () => {
    const options = withAttachedOptions(
      [{ value: 'mine', label: 'Mine' }],
      [
        { id: 'owners', label: 'Owner tool' },
        { id: 'unselected', label: 'Elsewhere' },
      ],
      ['mine', 'owners'],
      (name) => `${name} (added)`,
    );
    expect(options).toEqual([
      { value: 'mine', label: 'Mine' },
      { value: 'owners', label: 'Owner tool (added)' },
    ]);
  });

  it('falls back to the id when no name is known', () => {
    const options = withAttachedOptions([], [], ['x1'], (name) => name);
    expect(options).toEqual([{ value: 'x1', label: 'x1' }]);
  });
});

describe('confirmTakeOver', () => {
  const item = { key: 'tool:t1', type: 'tool' as const, id: 't1' };
  const audience = {
    teams: ['Sales'],
    api_key: true,
    public_link: false,
    webhook: false,
  };

  it('shows the item and who reaches it, and agrees when confirmed', async () => {
    const ask = vi.fn(() => Promise.resolve(['tool:t1']));
    await expect(confirmTakeOver(ask, item, 'Jira', audience)).resolves.toBe(
      true,
    );
    expect(ask).toHaveBeenCalledWith({
      resources: [{ ...item, name: 'Jira' }],
      audience,
    });
  });

  it('does not agree when the caller cancels', async () => {
    const ask = vi.fn(() => Promise.resolve(null));
    await expect(confirmTakeOver(ask, item, 'Jira', audience)).resolves.toBe(
      false,
    );
  });

  it('asks with an empty audience when the read sent none', async () => {
    const ask = vi.fn(() => Promise.resolve(['tool:t1']));
    await confirmTakeOver(ask, item, 'Jira', undefined);
    expect(ask).toHaveBeenCalledWith(
      expect.objectContaining({ audience: NO_AUDIENCE }),
    );
  });
});
