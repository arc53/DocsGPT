import apiClient from '../client';
import endpoints from '../endpoints';

export interface PersonalAccessToken {
  id: string;
  name: string;
  /** Display prefix only (e.g. `dgpt_pat_ab12cd`); never the full secret. */
  token_prefix: string;
  scopes: string[];
  /** `{family: [resource ids]}`; a missing family means "all resources". */
  resource_filter: Record<string, string[]>;
  status: string;
  expires_at: string | null;
  last_used_at: string | null;
  last_used_ip: string | null;
  created_at: string | null;
  /** Set once the secret has been regenerated; the lifetime then counts from here. */
  regenerated_at?: string | null;
  revoked_at: string | null;
}

export interface AccessTokenScope {
  name: string;
  description: string;
}

export interface AccessTokenPolicy {
  enabled: boolean;
  default_lifetime_days: number;
  max_lifetime_days: number;
  allow_non_expiring: boolean;
  max_per_user: number;
  filterable_families: string[];
}

export interface AccessTokenListResponse {
  tokens: PersonalAccessToken[];
  scopes: AccessTokenScope[];
  policy: AccessTokenPolicy;
}

export interface CreateAccessTokenPayload {
  name: string;
  scopes: string[];
  resource_filter?: Record<string, string[]>;
  /** `null`/omitted = server default, `0` = never expires. */
  expires_in_days?: number | null;
}

export interface CreateAccessTokenResponse {
  /** Plaintext secret. The server returns it exactly once. */
  token: string;
  personal_access_token: PersonalAccessToken;
}

/** Error carrying the server's user-facing `message` and the HTTP status. */
export class AccessTokenApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'AccessTokenApiError';
    this.status = status;
  }
}

// apiClient resolves to the raw fetch Response (the app convention). Parse it
// here and turn `{success:false, message}` / non-2xx into a thrown error so
// callers can show the server's message inline.
const parse = async <T>(response: Response): Promise<T> => {
  let body: { success?: boolean; message?: unknown } | null = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok || body?.success === false) {
    throw new AccessTokenApiError(
      typeof body?.message === 'string' ? body.message : '',
      response.status,
    );
  }
  return body as T;
};

const patService = {
  list: async (token: string | null): Promise<AccessTokenListResponse> =>
    parse<AccessTokenListResponse>(
      await apiClient.get(endpoints.USER.ACCESS_TOKENS, token),
    ),

  create: async (
    payload: CreateAccessTokenPayload,
    token: string | null,
  ): Promise<CreateAccessTokenResponse> =>
    parse<CreateAccessTokenResponse>(
      await apiClient.post(endpoints.USER.ACCESS_TOKENS, payload, token),
    ),

  /**
   * New secret for the same token (name, scopes and restrictions stay); the old
   * secret stops working at once. `expiresInDays` omitted = the lifetime the
   * token was last issued with.
   */
  regenerate: async (
    id: string,
    expiresInDays: number | undefined,
    token: string | null,
  ): Promise<CreateAccessTokenResponse> =>
    parse<CreateAccessTokenResponse>(
      await apiClient.post(
        endpoints.USER.ACCESS_TOKEN_REGENERATE(encodeURIComponent(id)),
        expiresInDays === undefined ? {} : { expires_in_days: expiresInDays },
        token,
      ),
    ),

  revoke: async (
    id: string,
    token: string | null,
  ): Promise<{ success: boolean }> =>
    parse<{ success: boolean }>(
      await apiClient.delete(
        endpoints.USER.ACCESS_TOKEN(encodeURIComponent(id)),
        token,
      ),
    ),
};

export default patService;
