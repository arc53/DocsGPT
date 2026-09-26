import { Plus } from 'lucide-react';
import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { MultiSelect } from '@/components/ui/multi-select';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

import {
  appendDocumentRef,
  documentsModeToInputDocuments,
  DocumentsMode,
  getDocumentsMode,
  withChosenDocumentOptions,
} from '../documentConfig';

interface NodeDocumentsControlProps {
  value: string[];
  onChange: (next: string[]) => void;
  options: { value: string; label: string }[];
  label: string;
  helpText?: string;
}

const MODE_OPTIONS: { mode: DocumentsMode; labelKey: string }[] = [
  { mode: 'all', labelKey: 'agents.workflow.documents.modeAll' },
  { mode: 'none', labelKey: 'agents.workflow.documents.modeNone' },
  { mode: 'choose', labelKey: 'agents.workflow.documents.modeChoose' },
];

/** Shared All/None/Choose documents picker for agent and code workflow nodes. */
export default function NodeDocumentsControl({
  value,
  onChange,
  options,
  label,
  helpText,
}: NodeDocumentsControlProps) {
  const { t } = useTranslation();
  // Track mode in component state so "Choose" stays reachable even when the
  // chosen list is empty (an empty list otherwise reads back as "None").
  const [mode, setMode] = useState<DocumentsMode>(() =>
    getDocumentsMode(value),
  );
  const [refDraft, setRefDraft] = useState('');
  const fieldId = useId();

  const chosen = documentsModeToInputDocuments('choose', value);
  const showChoose = mode === 'choose';

  const selectMode = (next: DocumentsMode) => {
    setMode(next);
    onChange(documentsModeToInputDocuments(next, chosen));
  };

  const addRef = () => {
    const next = appendDocumentRef(chosen, refDraft);
    setRefDraft('');
    if (next === chosen) return;
    setMode('choose');
    onChange(documentsModeToInputDocuments('choose', next));
  };

  return (
    <FormField label={label} hint={helpText} id={fieldId} float={false}>
      {/* The track is a plain wrapper: ToggleGroup takes layout only. */}
      <div className="border-border bg-card rounded-xl border p-1">
        <ToggleGroup
          id={fieldId}
          type="single"
          size="xs"
          value={mode}
          onValueChange={(next) => next && selectMode(next as DocumentsMode)}
          aria-label={label}
          className="flex-nowrap"
        >
          {MODE_OPTIONS.map(({ mode: optionMode, labelKey }) => (
            <ToggleGroupItem
              key={optionMode}
              value={optionMode}
              className="flex-1"
            >
              {t(labelKey)}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>
      {showChoose && (
        <div className="flex flex-col gap-2">
          <MultiSelect
            // Its own id: the FormField id belongs to the mode group above.
            id={`${fieldId}-pick`}
            options={withChosenDocumentOptions(options, chosen)}
            selected={chosen}
            onChange={(next) =>
              onChange(documentsModeToInputDocuments('choose', next))
            }
            placeholder={t('agents.workflow.documents.selectPlaceholder')}
            searchPlaceholder={t('agents.workflow.documents.searchPlaceholder')}
            emptyText={t('agents.workflow.documents.empty')}
          />
          <div className="flex gap-2">
            <Input
              id={`${fieldId}-ref`}
              type="text"
              value={refDraft}
              onChange={(e) => setRefDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addRef();
                }
              }}
              placeholder={t('agents.workflow.documents.refPlaceholder')}
            />
            <Button
              type="button"
              variant="ghost-muted"
              onClick={addRef}
              className="shrink-0"
            >
              <Plus className="size-3.5" />
              {t('agents.form.buttons.add')}
            </Button>
          </div>
        </div>
      )}
    </FormField>
  );
}
