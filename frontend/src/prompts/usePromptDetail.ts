import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import type { Prompt } from '../models/misc';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import { canEditPrompt, copyName } from './promptAccess';

/**
 * The prompt a detail view shows: a saved one (`edit`, read-only when the
 * role can't edit it), or a new one (Add, or a copy of `copyOf`), which
 * `draft` opens with the drafter's drawer.
 */
export type PromptDetailTarget =
  | { kind: 'edit'; prompt: Prompt }
  | { kind: 'new'; copyOf: string | null; draft: boolean };

/** How a save ended: a refused save over someone's newer edit is `conflict`. */
export type PromptSaveResult = 'saved' | 'conflict' | 'failed';

type PromptDetailOptions = {
  /** The listed prompts: a name must not repeat one, and a copy's is free. */
  prompts: Prompt[];
  /** A save went through: the prompt's id and name. */
  onSaved: (saved: { id: string; name: string }) => void;
};

/**
 * The state behind a prompt's detail view: which prompt is open, its name
 * and text, its loading, and Save. A saved prompt's text loads when it
 * opens and its version goes back with the save, so a save over someone
 * else's newer edit is refused (409) instead of overwriting it.
 *
 * Args:
 *   options: The listed prompts and the save callback.
 *
 * Returns:
 *   The open `target` (null for none) and a `key` that changes with every
 *   opening; `open`, `add`, `duplicate` and `close`; the fields and their
 *   setters; `status` of the text's load with `retry`; `readOnly`, `dirty`,
 *   `nameExists`, `canSave`, `saving`; and `save`.
 */
export function usePromptDetail({ prompts, onSaved }: PromptDetailOptions) {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);

  const [target, setTarget] = React.useState<PromptDetailTarget | null>(null);
  const [key, setKey] = React.useState(0);
  const [name, setName] = React.useState('');
  const [content, setContent] = React.useState('');
  // What the fields held when the prompt opened: leaving with other values
  // loses changes.
  const [baseline, setBaseline] = React.useState({ name: '', content: '' });
  const [updatedAt, setUpdatedAt] = React.useState<string | null>(null);
  const [status, setStatus] = React.useState<'loading' | 'error' | 'ready'>(
    'ready',
  );
  const [saving, setSaving] = React.useState(false);
  // The latest opening, so a load that lands after another one is dropped.
  const opening = React.useRef(0);

  const showError = (message: string) =>
    dispatch(showActionToast({ variant: 'destructive', message }));

  const fetchText = async (id: string) => {
    const response = await userService.getSinglePrompt(id, token);
    if (!response.ok) throw new Error('Failed to fetch prompt content');
    return (await response.json()) as {
      content: string;
      updated_at?: string | null;
    };
  };

  const show = (
    next: PromptDetailTarget,
    fields: { name: string; content: string },
  ) => {
    opening.current += 1;
    setTarget(next);
    setKey((value) => value + 1);
    setName(fields.name);
    setContent(fields.content);
    setBaseline(fields);
  };

  const load = (prompt: Prompt) => {
    const current = opening.current;
    setStatus('loading');
    fetchText(prompt.id)
      .then((loaded) => {
        if (opening.current !== current) return;
        setContent(loaded.content);
        setBaseline({ name: prompt.name, content: loaded.content });
        setUpdatedAt(loaded.updated_at ?? null);
        setStatus('ready');
      })
      .catch((error: unknown) => {
        console.error(error);
        if (opening.current === current) setStatus('error');
      });
  };

  /** Opens a saved prompt: to edit, or to read when the role can't edit it. */
  const open = (prompt: Prompt) => {
    show({ kind: 'edit', prompt }, { name: prompt.name, content: '' });
    setUpdatedAt(null);
    load(prompt);
  };

  /** Opens an empty new prompt. */
  const add = () => {
    show(
      { kind: 'new', copyOf: null, draft: false },
      { name: '', content: '' },
    );
    setStatus('ready');
  };

  /**
   * Opens a new prompt holding a copy of `prompt`, named so no listed one
   * repeats it. The open prompt is copied as it stands; another one loads
   * first. `draft` opens the drafter's drawer on the copy.
   */
  const duplicate = async (prompt: Prompt, { draft = false } = {}) => {
    let text = content;
    const isOpen =
      target?.kind === 'edit' &&
      target.prompt.id === prompt.id &&
      status === 'ready';
    if (!isOpen) {
      try {
        text = (await fetchText(prompt.id)).content;
      } catch (error) {
        console.error(error);
        showError(t('settings.prompts.loadPromptError'));
        return;
      }
    }
    show(
      { kind: 'new', copyOf: prompt.name, draft },
      { name: copyName(prompt.name, prompts), content: text },
    );
    setStatus('ready');
  };

  const close = () => {
    opening.current += 1;
    setTarget(null);
  };

  const retry = () => {
    if (target?.kind === 'edit') load(target.prompt);
  };

  const readOnly = target?.kind === 'edit' && !canEditPrompt(target.prompt);
  const dirty =
    !!target &&
    !readOnly &&
    (name !== baseline.name || content !== baseline.content);
  const nameExists = prompts.some(
    (prompt) =>
      prompt.name === name &&
      (target?.kind !== 'edit' || prompt.id !== target.prompt.id),
  );
  const canSave =
    !!target &&
    !readOnly &&
    status === 'ready' &&
    !!name &&
    !nameExists &&
    content.trim() !== '';

  /**
   * Saves the open prompt: creates a new one, or updates a saved one at the
   * version it opened with. A failure shows as a toast unless `quiet` (a
   * confirm dialog shows it itself).
   */
  const save = async ({ quiet = false } = {}): Promise<PromptSaveResult> => {
    if (!target || !canSave || saving) return 'failed';
    setSaving(true);
    let result: PromptSaveResult = 'failed';
    let savedId: string | null = null;
    try {
      if (target.kind === 'new') {
        const response = await userService.createPrompt(
          { name, content },
          token,
        );
        if (response.ok) {
          const created = (await response.json()) as { id?: string } | null;
          savedId = created?.id ?? null;
          result = savedId ? 'saved' : 'failed';
        }
      } else {
        const response = await userService.updatePrompt(
          {
            id: target.prompt.id,
            name,
            content,
            ...(updatedAt && { expected_updated_at: updatedAt }),
          },
          token,
        );
        if (response.ok) {
          savedId = target.prompt.id;
          result = 'saved';
        } else if (response.status === 409) result = 'conflict';
      }
    } catch (error) {
      console.error(error);
    } finally {
      setSaving(false);
    }
    if (result === 'saved' && savedId) {
      setBaseline({ name, content });
      onSaved({ id: savedId, name });
    } else if (!quiet) {
      showError(
        t(
          result === 'conflict'
            ? 'settings.prompts.editConflict'
            : 'settings.prompts.saveFailed',
        ),
      );
    }
    return result;
  };

  return {
    target,
    key,
    open,
    add,
    duplicate,
    close,
    name,
    setName,
    content,
    setContent,
    status,
    retry,
    readOnly,
    dirty,
    nameExists,
    canSave,
    saving,
    save,
  };
}

export type PromptDetail = ReturnType<typeof usePromptDetail>;
