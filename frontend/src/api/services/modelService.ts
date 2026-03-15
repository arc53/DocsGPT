import apiClient from '../client';
import endpoints from '../endpoints';

import type { AvailableModel, Model } from '../../models/types';

const modelService = {
  getModels: (token: string | null): Promise<Response> =>
    apiClient.get(endpoints.USER.MODELS, token, {}),

  transformModels: (models: AvailableModel[]): Model[] =>
    models.map((model) => ({
      id: model.id,
      value: model.id,
      provider: model.provider,
      display_name: model.display_name,
      description: model.description,
      context_window: model.context_window,
      supported_attachment_types: model.supported_attachment_types,
      supports_tools: model.supports_tools,
      supports_structured_output: model.supports_structured_output,
      supports_streaming: model.supports_streaming,
    })),
};

export default modelService;
