import apiClient from '../client';
import endpoints from '../endpoints';
import { workspaceHeader } from '../../workspace/requestWorkspace';

import type {
  CreateCustomModelPayload,
  CustomModel,
  CustomModelCapabilities,
  CustomModelDeleteResult,
  CustomModelOwner,
  CustomModelTestResult,
} from '../../models/types';

/**
 * Whose models to list. `owner: 'team'` reads the team's (any member);
 * `workspace` names the team to send it for, so an answer is filed under the
 * team it was asked for even if the user switches meanwhile.
 */
export type CustomModelListOptions = {
  owner?: CustomModelOwner;
  workspace?: string;
};

/**
 * A failed request's error: `status` and the parsed body in `payload`, to
 * word with `customModelRequestError` (`models/customModelErrors.ts`).
 */
export type CustomModelRequestError = Error & {
  status?: number;
  payload?: unknown;
};

const readBody = async (response: Response): Promise<any> => {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
};

const parseJsonOrError = async (response: Response): Promise<any> => {
  const body = await readBody(response);
  if (!response.ok) {
    const message =
      (body && (body.error || body.message)) ||
      `Request failed with status ${response.status}`;
    const err = new Error(message) as CustomModelRequestError;
    err.status = response.status;
    err.payload = body;
    throw err;
  }
  return body;
};

// A test answers 200 with `ok` either way; a refusal (a role, a model the
// caller can't see) keeps its code so the modal can word it.
const readTestResult = async (
  response: Response,
): Promise<CustomModelTestResult> => {
  const body = await readBody(response);
  if (!response.ok) {
    const result: CustomModelTestResult = {
      ok: false,
      error:
        (body && (body.error || body.message)) ||
        `Test failed with status ${response.status}`,
    };
    // A bare code, not a sentence such as a missing field's.
    if (
      body?.success === false &&
      typeof body.error === 'string' &&
      /^[a-z0-9_]+$/.test(body.error)
    )
      result.code = body.error;
    return result;
  }
  if (body && typeof body.ok === 'boolean') {
    return body as CustomModelTestResult;
  }
  return { ok: true };
};

const customModelsService = {
  /** The caller's own custom models, or a team's with `owner: 'team'`. */
  listCustomModels: async (
    token: string | null,
    options: CustomModelListOptions = {},
  ): Promise<CustomModel[]> => {
    const response = await apiClient.get(
      options.owner === 'team'
        ? endpoints.USER.CUSTOM_MODELS_TEAM
        : endpoints.USER.CUSTOM_MODELS,
      token,
      options.workspace ? workspaceHeader(options.workspace) : {},
    );
    const data = await parseJsonOrError(response);
    if (Array.isArray(data)) return data as CustomModel[];
    if (data && Array.isArray(data.models)) return data.models as CustomModel[];
    return [];
  },

  /** Adds a model; `owner: 'team'` adds it for the header's team (Admins). */
  createCustomModel: async (
    payload: CreateCustomModelPayload,
    token: string | null,
  ): Promise<CustomModel> => {
    const response = await apiClient.post(
      endpoints.USER.CUSTOM_MODELS,
      payload,
      token,
    );
    return (await parseJsonOrError(response)) as CustomModel;
  },

  updateCustomModel: async (
    id: string,
    payload: Partial<CreateCustomModelPayload>,
    token: string | null,
  ): Promise<CustomModel> => {
    const response = await apiClient.patch(
      endpoints.USER.CUSTOM_MODEL(id),
      payload,
      token,
    );
    return (await parseJsonOrError(response)) as CustomModel;
  },

  /**
   * Deletes a model. A team's model answers with `usage`: the team's agents
   * and workflows that named it, which now run on the default model.
   */
  deleteCustomModel: async (
    id: string,
    token: string | null,
  ): Promise<CustomModelDeleteResult> => {
    const response = await apiClient.delete(
      endpoints.USER.CUSTOM_MODEL(id),
      token,
    );
    const body = await parseJsonOrError(response);
    return body && typeof body === 'object' ? body : { success: true };
  },

  /**
   * Copies the caller's own model into a team they are an Admin of, its key
   * sealed for the team; their model stays as it was. Answers the team's
   * new row; a refusal throws (409 `model_already_in_team` with `model_id`,
   * 409 `credentials_unreadable`, 403 `workspace_role_required`, …).
   */
  copyToTeam: async (
    id: string,
    teamId: string,
    token: string | null,
  ): Promise<CustomModel> => {
    const response = await apiClient.post(
      endpoints.USER.CUSTOM_MODEL_COPY(id),
      { team_id: teamId },
      token,
    );
    return (await parseJsonOrError(response)) as CustomModel;
  },

  /** Tests an unsaved model; `owner: 'team'` while adding one for the team. */
  testCustomModelPayload: async (
    payload: {
      base_url: string;
      api_key: string;
      upstream_model_id: string;
      capabilities?: Pick<CustomModelCapabilities, 'api_flavor'>;
      owner?: CustomModelOwner;
    },
    token: string | null,
  ): Promise<CustomModelTestResult> => {
    const response = await apiClient.post(
      endpoints.USER.CUSTOM_MODEL_TEST_PAYLOAD,
      payload,
      token,
    );
    return readTestResult(response);
  },

  testCustomModel: async (
    id: string,
    token: string | null,
    overrides: {
      base_url?: string;
      api_key?: string;
      upstream_model_id?: string;
      capabilities?: Pick<CustomModelCapabilities, 'api_flavor'>;
    } = {},
  ): Promise<CustomModelTestResult> => {
    // Send only non-empty overrides; server falls back to stored values.
    const requestBody: Record<string, unknown> = {};
    if (overrides.base_url) requestBody.base_url = overrides.base_url;
    if (overrides.api_key) requestBody.api_key = overrides.api_key;
    if (overrides.upstream_model_id)
      requestBody.upstream_model_id = overrides.upstream_model_id;
    if (overrides.capabilities)
      requestBody.capabilities = overrides.capabilities;
    const response = await apiClient.post(
      endpoints.USER.CUSTOM_MODEL_TEST(id),
      requestBody,
      token,
    );
    return readTestResult(response);
  },
};

export default customModelsService;
