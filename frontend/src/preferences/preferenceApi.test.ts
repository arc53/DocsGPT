import conversationService from '../api/services/conversationService';
import { getConversations } from './preferenceApi';

vi.mock('../api/services/conversationService', () => ({
  default: { getConversations: vi.fn() },
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
