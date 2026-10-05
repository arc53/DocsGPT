import { useEffect, useState } from 'react';

import modelService from '../../api/services/modelService';
import userService from '../../api/services/userService';
import type { Model } from '../../models/types';

/**
 * What RetrievalOptions may offer on this instance: the hybrid and graphrag
 * retrievers (from /api/config) and, when graphrag is on, the models for its
 * extraction-model picker. Nothing is fetched until `enabled`.
 */
export default function useRetrievalAvailability(
  token: string | null,
  enabled = true,
) {
  const [graphRAGAvailable, setGraphRAGAvailable] = useState(false);
  const [hybridAvailable, setHybridAvailable] = useState(false);
  const [availableModels, setAvailableModels] = useState<Model[]>([]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    userService
      .getConfig()
      .then((response) => response.json())
      .then((config) => {
        if (!cancelled) {
          setGraphRAGAvailable(!!config?.graphrag_available);
          setHybridAvailable(!!config?.hybrid_available);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  // Models back the graphrag extraction-model picker; only fetched when the
  // instance supports graphrag.
  useEffect(() => {
    if (!enabled || !graphRAGAvailable) return;
    let cancelled = false;
    modelService
      .getModels(token)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (!cancelled && data)
          setAvailableModels(modelService.transformModels(data.models || []));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [enabled, graphRAGAvailable, token]);

  return { graphRAGAvailable, hybridAvailable, availableModels };
}
