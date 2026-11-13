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
  /** A model id, `defaultValue`, or `TASK_MODEL_UNAVAILABLE`. */
  value: string;
  onChange: (value: string) => void;
  /** The value of the first option, no model of the caller's own. */
  defaultValue: string;
  /** That option's label, naming the model that runs then when there is one. */
  defaultLabel: string;
  /** The label without the model's name: a phone's trigger shows it when the two differ. */
  defaultShortLabel: string;
  /** The model options; a group with a label is listed under it, and only when it has models. */
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
 * Select whose first option is the default, then the models, a model
 * whose provider refused its key marked in the list. A stored model that
 * can't run shows no option and a warning; else, while the refused model
 * is the one that runs, a warning names it. The trigger grows with its
 * value up to 384px, then ends in "…" with the whole name as its title.
 * The page passes its own strings.
 */
export default function TaskModelRow({
  id,
  label,
  description,
  value,
  onChange,
  defaultValue,
  defaultLabel,
  defaultShortLabel,
  groups,
  runningModelId,
  refusedModelId,
  unavailableValue,
  refusedSuffix,
  unavailableNote,
  refusedNote,
}: TaskModelRowProps) {
  const models = groups.flatMap((group) => group.models);
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
  const pickedLabel =
    value === defaultValue
      ? defaultLabel
      : models.find((m) => m.id === value)?.display_name;
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
          // Grows to its value, up to 384px (room for the default's label
          // with its model), then ends in "…" (the whole name as its title).
          className="w-full sm:w-auto sm:max-w-96 sm:min-w-56"
          size="field"
          shape="pill"
          title={pickedLabel}
        >
          <SelectValue placeholder={unavailableValue}>
            {value === defaultValue && defaultLabel !== defaultShortLabel ? (
              // A phone's full-width trigger (16px text) can't fit the
              // model's name as well: it shows the choice, and the list and
              // the title name the model.
              <>
                <span className="truncate sm:hidden">{defaultShortLabel}</span>
                <span className="hidden truncate sm:block">{defaultLabel}</span>
              </>
            ) : undefined}
          </SelectValue>
        </SelectTrigger>
        <SelectContent fit>
          <SelectItem value={defaultValue}>
            <span className="truncate">{defaultLabel}</span>
          </SelectItem>
          {groups.map((group, index) =>
            group.label === undefined ? (
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
