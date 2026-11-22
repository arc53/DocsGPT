import { Fragment } from 'react';

import { Alert, AlertDescription } from '../../components/ui/alert';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '../../components/ui/select';
import { SettingRow } from '../../components/ui/setting-row';

/**
 * A stored task model that can't run (a disabled or deleted model): the
 * default runs meanwhile, and the stored one again if it comes back. No
 * option shows it, so picking any one replaces it.
 */
export const TASK_MODEL_UNAVAILABLE = '__unavailable__';

/** The model a `task_model_error` names, when it is a refused key (code `model_auth`); else null. */
export const refusedModel = (error: unknown): string | null => {
  if (!error || typeof error !== 'object') return null;
  const { model_id: modelId, code } = error as {
    model_id?: unknown;
    code?: unknown;
  };
  return code === 'model_auth' && typeof modelId === 'string' && modelId
    ? modelId
    : null;
};

type TaskModelOption = { id: string; display_name: string };

type TaskModelRowProps = {
  id: string;
  label: string;
  description: string;
  /** A model id, `TASK_MODEL_UNAVAILABLE`, or `''` while no model is picked. */
  value: string;
  /** Called with the picked model's id. */
  onChange: (modelId: string) => void;
  /** The value shown while no model is picked. */
  placeholder: string;
  /**
   * The model options, group by group. Each group with models is listed under
   * its label once two of them have models; alone, it needs no heading.
   */
  groups: { label?: string; models: TaskModelOption[] }[];
  /** The model that runs now. */
  runningModelId: string | null;
  /** The model whose provider refused its key on its last task; null when none did. */
  refusedModelId: string | null;
  /** The value shown for a stored model that can't run. */
  unavailableValue: string;
  /** The list's mark on the refused model. */
  refusedSuffix: string;
  /** The warning while the stored model can't run. */
  unavailableNote: string;
  /** The warning while the refused model is the one that runs. */
  refusedNote: (model: string) => string;
};

/**
 * The task model row of Settings › General and Admin › Defaults: a pill
 * Select of the models alone, as in the chat's picker, a model whose
 * provider refused its key marked in the list. The page decides which model
 * shows as picked while none is stored (the one that runs then). The list
 * sizes to its options and stops at a long list's height. A stored model
 * that can't run shows no option and a warning; else, while the refused
 * model is the one that runs, a warning names it. The trigger grows with
 * its value up to 384px, then ends in "…" with the whole name as its title.
 * The page passes its own strings.
 */
export default function TaskModelRow({
  id,
  label,
  description,
  value,
  onChange,
  placeholder,
  groups,
  runningModelId,
  refusedModelId,
  unavailableValue,
  refusedSuffix,
  unavailableNote,
  refusedNote,
}: TaskModelRowProps) {
  const models = groups.flatMap((group) => group.models);
  // Headings only once there are groups to tell apart, as in the chat's picker.
  const headed = groups.filter((group) => group.models.length > 0).length > 1;
  const nameOf = (modelId: string) =>
    models.find((m) => m.id === modelId)?.display_name ?? modelId;
  const refused =
    refusedModelId !== null && refusedModelId === runningModelId
      ? nameOf(refusedModelId)
      : null;
  const note =
    value === TASK_MODEL_UNAVAILABLE
      ? unavailableNote
      : refused
        ? refusedNote(refused)
        : null;
  const pickedLabel = models.find((m) => m.id === value)?.display_name;
  const renderItem = (model: TaskModelOption) => (
    <SelectItem
      key={model.id}
      value={model.id}
      suffix={model.id === refusedModelId ? refusedSuffix : undefined}
    >
      <span className="truncate">{model.display_name}</span>
    </SelectItem>
  );

  return (
    <SettingRow
      label={label}
      description={description}
      htmlFor={id}
      stack
      after={
        note ? (
          <Alert variant="warning">
            <AlertDescription>{note}</AlertDescription>
          </Alert>
        ) : undefined
      }
    >
      <Select
        value={value === TASK_MODEL_UNAVAILABLE ? '' : value}
        onValueChange={onChange}
      >
        <SelectTrigger
          id={id}
          // Grows to its value, up to 384px, then ends in "…" (the whole
          // name as its title).
          className="w-full sm:w-auto sm:max-w-96 sm:min-w-56"
          size="field"
          shape="pill"
          title={pickedLabel}
        >
          <SelectValue
            placeholder={
              value === TASK_MODEL_UNAVAILABLE ? unavailableValue : placeholder
            }
          />
        </SelectTrigger>
        <SelectContent fit capped>
          {groups.map((group, index) =>
            !headed || group.label === undefined ? (
              <Fragment key={index}>{group.models.map(renderItem)}</Fragment>
            ) : group.models.length > 0 ? (
              <SelectGroup key={index}>
                <SelectLabel>{group.label}</SelectLabel>
                {group.models.map(renderItem)}
              </SelectGroup>
            ) : null,
          )}
        </SelectContent>
      </Select>
    </SettingRow>
  );
}
