import conversationService from '../api/services/conversationService';
import userService from '../api/services/userService';
import { getConversations, getDocsWithPagination } from './preferenceApi';

vi.mock('../api/services/conversationService', () => ({
  default: { getConversations: vi.fn() },
}));
vi.mock('../api/services/userService', () => ({
  default: { getDocsWithPagination: vi.fn() },
}));

const listing = (rows: unknown[]) =>
  vi
    .mocked(conversationService.getConversations)
    .mockResolvedValue({ ok: true, json: async () => rows } as Response);

describe('getConversations', () => {
  it("keeps each chat's unread mark from the server", async () => {
    listing([
      { id: 'c1', name: 'One', agent_id: null, date: 'd1', unread: true },
      { id: 'c2', name: 'Two', agent_id: null, date: 'd2', unread: false },
    ]);
    const { data } = await getConversations('tok');
    expect(data?.map((chat) => chat.unread)).toEqual([true, false]);
  });

  it('leaves the mark out when the server sends none', async () => {
    listing([{ id: 'c1', name: 'One', agent_id: null, date: 'd1' }]);
    const { data } = await getConversations('tok');
    expect(data?.[0]).not.toHaveProperty('unread');
  });

  it('stamps when the request went out, for marks changed while it ran', async () => {
    listing([]);
    const before = Date.now();
    const result = await getConversations('tok');
    expect(result.requestedAt).toBeGreaterThanOrEqual(before);
    expect(result.requestedAt).toBeLessThanOrEqual(Date.now());
  });
});

describe('getDocsWithPagination', () => {
  const listed = () => {
    vi.mocked(userService.getDocsWithPagination).mockResolvedValue({
      ok: true,
      json: async () => ({ paginated: [], total: 0, subtree_total: 7 }),
    } as Response);
    return vi.mocked(userService.getDocsWithPagination);
  };

  it('scopes the listing to a folder, its own sources or its subtree', async () => {
    const service = listed();
    const page = await getDocsWithPagination('date', 'desc', 1, 12, '', null, {
      scope: { folder: 'f-1', direct: true },
    });
    expect(service.mock.lastCall![0]).toContain('&folder=f-1&direct=true');
    expect(page?.subtreeTotal).toBe(7);
    await getDocsWithPagination('date', 'desc', 1, 12, 'a&b', null, {
      scope: { folder: 'root', direct: false },
    });
    expect(service.mock.lastCall![0]).toContain(
      'search=a%26b&folder=root&direct=false',
    );
  });

  it('sends no folder without a scope', async () => {
    const service = listed();
    await getDocsWithPagination('date', 'desc', 1, 12, '', null);
    expect(service.mock.lastCall![0]).not.toContain('folder=');
  });
});
