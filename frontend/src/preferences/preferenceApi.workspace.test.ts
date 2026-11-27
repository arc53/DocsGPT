import userService from '../api/services/userService';
import { getDocsWithPagination } from './preferenceApi';

vi.mock('../api/services/userService', () => ({
  default: { getDocsWithPagination: vi.fn() },
}));

describe('getDocsWithPagination origin', () => {
  const listed = () => {
    vi.mocked(userService.getDocsWithPagination).mockResolvedValue({
      ok: true,
      json: async () => ({
        paginated: [],
        total: 0,
        origin_counts: { own: 4, shared: 2 },
      }),
    } as Response);
    return vi.mocked(userService.getDocsWithPagination);
  };

  it('asks for one origin and reads the counts of both', async () => {
    const service = listed();
    const page = await getDocsWithPagination('date', 'desc', 1, 12, '', null, {
      origin: 'shared',
    });
    expect(service.mock.lastCall![2]).toBe('shared');
    expect(page?.originCounts).toEqual({ own: 4, shared: 2 });
  });

  it('asks for every origin when none is named', async () => {
    const service = listed();
    await getDocsWithPagination('date', 'desc', 1, 12, '', null);
    expect(service.mock.lastCall![2]).toBeUndefined();
  });
});
