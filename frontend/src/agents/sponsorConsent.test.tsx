import type { MultiSelectPopoverItem } from '../components/MultiSelectPopover';
import { readSponsorRefusal, withAttachedToolRows } from './sponsorConsent';

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
