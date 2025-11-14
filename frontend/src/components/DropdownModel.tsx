import React, { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import modelService from '../api/services/modelService';
import Arrow2 from '../assets/dropdown-arrow.svg';
import RoundedTick from '../assets/rounded-tick.svg';
import {
  selectAvailableModels,
  selectSelectedModel,
  setAvailableModels,
  setModelsLoading,
  setSelectedModel,
} from '../preferences/preferenceSlice';

import type { Model } from '../models/types';

export default function DropdownModel() {
  const dispatch = useDispatch();
  const selectedModel = useSelector(selectSelectedModel);
  const availableModels = useSelector(selectAvailableModels);
  const dropdownRef = React.useRef<HTMLDivElement>(null);
  const [isOpen, setIsOpen] = React.useState(false);

  useEffect(() => {
    const loadModels = async () => {
      if ((availableModels?.length ?? 0) > 0) {
        return;
      }
      dispatch(setModelsLoading(true));
      try {
        const response = await modelService.getModels(null);
        if (!response.ok) {
          throw new Error(`API error: ${response.status}`);
        }
        const data = await response.json();
        const models = data.models || [];
        const transformed = modelService.transformModels(models);

        dispatch(setAvailableModels(transformed));
        if (!selectedModel && transformed.length > 0) {
          const defaultModel =
            transformed.find((m) => m.id === data.default_model_id) ||
            transformed[0];
          dispatch(setSelectedModel(defaultModel));
        } else if (selectedModel && transformed.length > 0) {
          const isValid = transformed.find((m) => m.id === selectedModel.id);
          if (!isValid) {
            const defaultModel =
              transformed.find((m) => m.id === data.default_model_id) ||
              transformed[0];
            dispatch(setSelectedModel(defaultModel));
          }
        }
      } catch (error) {
        console.error('Failed to load models:', error);
      } finally {
        dispatch(setModelsLoading(false));
      }
    };

    loadModels();
  }, [availableModels?.length, dispatch, selectedModel]);

  const handleClickOutside = (event: MouseEvent) => {
    if (
      dropdownRef.current &&
      !dropdownRef.current.contains(event.target as Node)
    ) {
      setIsOpen(false);
    }
  };

  useEffect(() => {
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  return (
    <div ref={dropdownRef}>
      <div
        className={`bg-gray-1000 dark:bg-dark-charcoal mx-auto flex w-full cursor-pointer justify-between p-1 dark:text-white ${isOpen ? 'rounded-t-3xl' : 'rounded-3xl'}`}
        onClick={() => setIsOpen(!isOpen)}
      >
        {selectedModel?.display_name ? (
          <p className="mx-4 my-3 truncate overflow-hidden whitespace-nowrap">
            {selectedModel.display_name}
          </p>
        ) : (
          <p className="mx-4 my-3 truncate overflow-hidden whitespace-nowrap">
            Select Model
          </p>
        )}
        <img
          src={Arrow2}
          alt="arrow"
          className={`${
            isOpen ? 'rotate-360' : 'rotate-270'
          } mr-3 w-3 transition-all select-none`}
        />
      </div>
      {isOpen && (
        <div className="no-scrollbar dark:bg-dark-charcoal absolute right-0 left-0 z-20 -mt-1 max-h-52 w-full overflow-y-auto rounded-b-3xl bg-white shadow-md">
          {availableModels && (availableModels?.length ?? 0) > 0 ? (
            availableModels.map((model: Model) => (
              <div
                key={model.id}
                onClick={() => {
                  dispatch(setSelectedModel(model));
                  setIsOpen(false);
                }}
                className={`border-gray-3000/75 dark:border-purple-taupe/50 hover:bg-gray-3000/75 dark:hover:bg-purple-taupe flex h-10 w-full cursor-pointer items-center justify-between border-t`}
              >
                <div className="flex w-full items-center justify-between">
                  <p className="overflow-hidden py-3 pr-2 pl-5 overflow-ellipsis whitespace-nowrap">
                    {model.display_name}
                  </p>
                  {model.id === selectedModel?.id ? (
                    <img
                      src={RoundedTick}
                      alt="selected"
                      className="mr-3.5 h-4 w-4"
                    />
                  ) : null}
                </div>
              </div>
            ))
          ) : (
            <div className="h-10 w-full border-x-2 border-b-2">
              <p className="ml-5 py-3 text-gray-500">No models available</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
