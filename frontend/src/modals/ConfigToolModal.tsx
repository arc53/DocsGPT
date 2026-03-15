import React, { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import ConfigFields from '../components/ConfigFields';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import { AvailableToolType } from './types';
import WrapperModal from './WrapperModal';

interface ConfigToolModalProps {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  tool: AvailableToolType | null;
  getUserTools: () => void;
}

export default function ConfigToolModal({
  modalState,
  setModalState,
  tool,
  getUserTools,
}: ConfigToolModalProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [configValues, setConfigValues] = useState<{ [key: string]: any }>({});
  const [customName, setCustomName] = useState('');
  const [errors, setErrors] = useState<{ [key: string]: string }>({});
  const [saving, setSaving] = useState(false);

  const configRequirements = useMemo(
    () => tool?.configRequirements ?? {},
    [tool],
  );

  const hasConfig = Object.keys(configRequirements).length > 0;

  const handleFieldChange = (key: string, value: any) => {
    setConfigValues((prev) => ({ ...prev, [key]: value }));
    if (errors[key]) setErrors((prev) => ({ ...prev, [key]: '' }));
  };

  const validate = () => {
    const newErrors: { [key: string]: string } = {};
    Object.entries(configRequirements).forEach(([key, spec]) => {
      if (spec.depends_on) {
        const visible = Object.entries(spec.depends_on).every(
          ([dk, dv]) => configValues[dk] === dv,
        );
        if (!visible) return;
      }
      if (spec.required && !configValues[key]?.toString().trim()) {
        newErrors[key] = `${spec.label || key} is required`;
      }
      if (spec.type === 'number' && configValues[key] !== undefined) {
        const num = Number(configValues[key]);
        if (isNaN(num) || num < 1) {
          newErrors[key] = 'Must be a positive number';
        }
        if (key === 'timeout' && num > 300) {
          newErrors[key] = 'Maximum timeout is 300 seconds';
        }
      }
    });
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleClose = () => {
    setModalState('INACTIVE');
    setConfigValues({});
    setCustomName('');
    setErrors({});
  };

  const handleAddTool = () => {
    if (!tool || !validate()) return;

    const config: { [key: string]: any } = {};
    Object.entries(configRequirements).forEach(([key, spec]) => {
      const val = configValues[key];
      if (val !== undefined && val !== '') {
        config[key] = val;
      } else if (spec.default !== undefined) {
        config[key] = spec.default;
      }
    });

    setSaving(true);
    userService
      .createTool(
        {
          name: tool.name,
          displayName: tool.displayName,
          description: tool.description,
          config,
          customName,
          actions: tool.actions,
          status: true,
        },
        token,
      )
      .then(() => {
        handleClose();
        getUserTools();
      })
      .finally(() => setSaving(false));
  };

  if (modalState !== 'ACTIVE' || !tool) return null;

  return (
    <WrapperModal close={handleClose}>
      <div className="w-[400px] max-w-[90vw]">
        <h2 className="text-eerie-black dark:text-bright-gray text-xl font-semibold">
          {t('modals.configTool.title')}
        </h2>
        <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
          {t('modals.configTool.type')}:{' '}
          <span className="font-medium text-gray-700 dark:text-gray-200">
            {tool.displayName}
          </span>
        </p>

        <div className="mt-6 flex flex-col gap-4 px-1">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="customName">
              {t('modals.configTool.customNamePlaceholder')}
            </Label>
            <Input
              id="customName"
              type="text"
              value={customName}
              onChange={(e) => setCustomName(e.target.value)}
              placeholder={tool.displayName}
              className="rounded-xl"
            />
          </div>

          {hasConfig && <ConfigFields
            configRequirements={configRequirements}
            values={configValues}
            onChange={handleFieldChange}
            errors={errors}
          />}
        </div>

        <div className="mt-8 flex flex-row-reverse gap-2">
          <button
            onClick={handleAddTool}
            disabled={saving}
            className="bg-purple-30 hover:bg-violets-are-blue disabled:opacity-60 rounded-full px-5 py-2 text-sm font-medium text-white transition-colors"
          >
            {saving
              ? t('modals.configTool.addButton') + '…'
              : t('modals.configTool.addButton')}
          </button>
          <button
            onClick={handleClose}
            className="dark:text-light-gray cursor-pointer rounded-full px-5 py-2 text-sm font-medium hover:bg-gray-100 dark:bg-transparent dark:hover:bg-[#767183]/50"
          >
            {t('modals.configTool.closeButton')}
          </button>
        </div>
      </div>
    </WrapperModal>
  );
}
