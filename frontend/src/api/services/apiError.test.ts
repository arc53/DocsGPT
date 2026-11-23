import { ApiError, apiErrorFrom, readRefusal } from './apiError';

class ThingsApiError extends ApiError {
  constructor(...args: ConstructorParameters<typeof ApiError>) {
    super(...args);
    this.name = 'ThingsApiError';
  }
}

const answer = (status: number, body: unknown) =>
  ({
    ok: false,
    status,
    json: async () => {
      if (typeof body === 'string') throw new SyntaxError('not JSON');
      return body;
    },
  }) as Response;

describe('apiError', () => {
  it("reads a refusal's code, message and body", async () => {
    const body = { error: 'team_locked', message: 'Locked', counts: { a: 1 } };
    expect(await readRefusal(answer(409, body))).toEqual({
      code: 'team_locked',
      message: 'Locked',
      body,
    });
  });

  it('reads nothing from an answer that is not JSON', async () => {
    expect(await readRefusal(answer(502, '<html>'))).toEqual({});
  });

  it("throws the service's own class with the server's words", async () => {
    const error = await apiErrorFrom(
      answer(403, { error: 'workspace_role_required', message: 'Admins only' }),
      ThingsApiError,
    );
    expect(error).toBeInstanceOf(ThingsApiError);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toBeInstanceOf(Error);
    expect(error.name).toBe('ThingsApiError');
    expect(error.status).toBe(403);
    expect(error.code).toBe('workspace_role_required');
    expect(error.message).toBe('Admins only');
    expect(error.body).toEqual({
      error: 'workspace_role_required',
      message: 'Admins only',
    });
  });

  it('falls back to the code only when asked, else to the status', async () => {
    const codeOnly = { error: 'last_admin' };
    expect(
      (await apiErrorFrom(answer(409, codeOnly), ThingsApiError)).message,
    ).toBe('Request failed (409)');
    expect(
      (
        await apiErrorFrom(answer(409, codeOnly), ThingsApiError, {
          codeAsMessage: true,
        })
      ).message,
    ).toBe('last_admin');
    const bare = await apiErrorFrom(answer(404, '<html>'), ThingsApiError, {
      codeAsMessage: true,
    });
    expect(bare.message).toBe('Request failed (404)');
    expect(bare.code).toBeUndefined();
    expect(bare.body).toBeUndefined();
  });
});
