const service = vi.hoisted(() => ({
  getDocsWithPagination: vi.fn(),
}));

vi.mock('../api/services/userService', () => ({ default: service }));

import { getDocsWithPagination } from './preferenceApi';

describe('getDocsWithPagination', () => {
  beforeEach(() => {
    service.getDocsWithPagination.mockReset();
  });

  it('URL-encodes reserved characters in the search term', async () => {
    service.getDocsWithPagination.mockResolvedValue({
      ok: true,
      json: async () => ({
        paginated: [],
        total: 0,
        totalPages: 0,
        currentPage: 2,
      }),
    });

    await getDocsWithPagination('name', 'asc', 2, 25, 'C++ & #tag', 'token');

    expect(service.getDocsWithPagination).toHaveBeenCalledWith(
      'sort=name&order=asc&page=2&rows=25&search=C%2B%2B+%26+%23tag',
      'token',
    );
  });
});
