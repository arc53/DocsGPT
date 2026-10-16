import { describe, expect, it, vi } from 'vitest';
import userService from '../api/services/userService';
import { getDocsWithPagination } from './preferenceApi';

vi.mock('../api/services/userService', () => ({
  default: {
    getDocsWithPagination: vi.fn(),
  },
}));

describe('getDocsWithPagination', () => {
  it('URL-encodes search terms containing reserved URL characters like #, &, +, and spaces', async () => {
    const mockResponse = {
      ok: true,
      json: async () => ({
        paginated: [],
        total: 0,
        totalPages: 0,
        currentPage: 1,
      }),
    };
    vi.mocked(userService.getDocsWithPagination).mockResolvedValue(
      mockResponse as unknown as Response,
    );

    const searchTerm = '#definitely-not-present & + test';
    await getDocsWithPagination(
      'date',
      'desc',
      1,
      10,
      searchTerm,
      'mock-token',
    );

    expect(userService.getDocsWithPagination).toHaveBeenCalledWith(
      'sort=date&order=desc&page=1&rows=10&search=%23definitely-not-present+%26+%2B+test',
      'mock-token',
    );
  });
});
