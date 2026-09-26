import React, { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import ConfigFields from '../components/ConfigFields';
import { FormField } from '../components/ui/form-field';
import { Input } from '../components/ui/input';
import { Modal, ModalActions } from '../components/ui/modal';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import { AvailableToolType } from './types';

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
        newErrors[key] = t('modals.configTool.fieldRequired', {
          field: spec.label || key,
        });
      }
      if (spec.type === 'number' && configValues[key] !== undefined) {
        const num = Number(configValues[key]);
        if (isNaN(num) || num < 1) {
          newErrors[key] = t('modals.configTool.positiveNumber');
        }
        if (key === 'timeout' && num > 300) {
          newErrors[key] = t('modals.configTool.maxTimeout');
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

  if (!tool) return null;

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={(o) => !o && handleClose()}
      title={t('modals.configTool.title')}
      size="lg"
      footer={
        <ModalActions
          cancelLabel={t('modals.configTool.closeButton')}
          onCancel={handleClose}
          submitLabel={t('modals.configTool.addButton')}
          onSubmit={handleAddTool}
          pending={saving}
        />
      }
    >
      <div>
        <p className="text-muted-foreground mt-2 text-sm">
          {t('modals.configTool.type')}:{' '}
          <span className="text-foreground font-medium">
            {tool.displayName}
          </span>
        </p>

        <div className="mt-6 flex flex-col gap-5">
          <FormField label={t('modals.configTool.customNamePlaceholder')}>
            <Input
              type="text"
              value={customName}
              onChange={(e) => setCustomName(e.target.value)}
              placeholder={tool.displayName}
            />
          </FormField>

          {hasConfig && (
            <ConfigFields
              configRequirements={configRequirements}
              values={configValues}
              onChange={handleFieldChange}
              errors={errors}
            />
          )}
        </div>
      </div>
    </Modal>
  );
}
