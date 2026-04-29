import apiClient from '../client';
import endpoints from '../endpoints';

import type {
  CreateCustomModelPayload,
  CustomModel,
  CustomModelTestResult,
} from '../../models/types';

const parseJsonOrError = async (response: Response): Promise<any> => {
  const text = await response.text();
  let body: any = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }
  if (!response.ok) {
    const message =
      (body && (body.error || body.message)) ||
      `Request failed with status ${response.status}`;
    const err = new Error(message) as Error & {
      status?: number;
      payload?: unknown;
    };
    err.status = response.status;
    err.payload = body;
    throw err;
  }
  return body;
};

const customModelsService = {
  listCustomModels: async (token: string | null): Promise<CustomModel[]> => {
    const response = await apiClient.get(endpoints.USER.CUSTOM_MODELS, token);
    const data = await parseJsonOrError(response);
    if (Array.isArray(data)) return data as CustomModel[];
    if (data && Array.isArray(data.models)) return data.models as CustomModel[];
    return [];
  },

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

  deleteCustomModel: async (
    id: string,
    token: string | null,
  ): Promise<void> => {
    const response = await apiClient.delete(
      endpoints.USER.CUSTOM_MODEL(id),
      token,
    );
    if (!response.ok) {
      await parseJsonOrError(response);
    }
  },

  testCustomModelPayload: async (
    payload: {
      base_url: string;
      api_key: string;
      upstream_model_id: string;
    },
    token: string | null,
  ): Promise<CustomModelTestResult> => {
    const response = await apiClient.post(
      endpoints.USER.CUSTOM_MODEL_TEST_PAYLOAD,
      payload,
      token,
    );
    const text = await response.text();
    let body: any = null;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = null;
      }
    }
    if (!response.ok) {
      return {
        ok: false,
        error:
          (body && (body.error || body.message)) ||
          `Test failed with status ${response.status}`,
      };
    }
    if (body && typeof body.ok === 'boolean') {
      return body as CustomModelTestResult;
    }
    return { ok: true };
  },

  testCustomModel: async (
    id: string,
    token: string | null,
    overrides: {
      base_url?: string;
      api_key?: string;
      upstream_model_id?: string;
    } = {},
  ): Promise<CustomModelTestResult> => {
    // Send only non-empty overrides; server falls back to stored values.
    const requestBody: Record<string, string> = {};
    if (overrides.base_url) requestBody.base_url = overrides.base_url;
    if (overrides.api_key) requestBody.api_key = overrides.api_key;
    if (overrides.upstream_model_id)
      requestBody.upstream_model_id = overrides.upstream_model_id;
    const response = await apiClient.post(
      endpoints.USER.CUSTOM_MODEL_TEST(id),
      requestBody,
      token,
    );
    const text = await response.text();
    let body: any = null;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = null;
      }
    }
    if (!response.ok) {
      return {
        ok: false,
        error:
          (body && (body.error || body.message)) ||
          `Test failed with status ${response.status}`,
      };
    }
    if (body && typeof body.ok === 'boolean') {
      return body as CustomModelTestResult;
    }
    return { ok: true };
  },
};

export default customModelsService;
