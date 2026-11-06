import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import type { Prompt } from '../models/misc';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import { canEditPrompt, copyName } from './promptAccess';
import { templateBroken } from './promptTemplate';

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

/** What in the fields keeps an editable, loaded prompt from saving. */
export type PromptSaveBlocker = 'name' | 'nameExists' | 'content' | 'template';

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
 *   opening; `open`, `add`, `duplicate`, `openWith` and `close`; the
 *   fields and their setters; `status` of the text's load with `retry`;
 *   `readOnly`, `dirty`, `nameExists`, `canSave` with `saveBlocker` (what
 *   in the fields stops it), `saving`; and `save`.
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
  // Each prompt's version as last loaded or saved here, so reopening one
  // with drafted text (openWith) still saves at the version it is on.
  const versions = React.useRef(new Map<string, string | null>());

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
        versions.current.set(prompt.id, loaded.updated_at ?? null);
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
      // Another opening while the text loads wins over this copy.
      const current = opening.current;
      try {
        text = (await fetchText(prompt.id)).content;
      } catch (error) {
        console.error(error);
        if (opening.current === current)
          showError(t('settings.prompts.loadPromptError'));
        return;
      }
      if (opening.current !== current) return;
    }
    show(
      { kind: 'new', copyOf: prompt.name, draft },
      { name: copyName(prompt.name, prompts), content: text },
    );
    setStatus('ready');
  };

  /**
   * Opens a prompt holding text the drafter wrote, with nothing to load: a
   * new prompt, or `prompt` (one the host created earlier from a draft), so
   * Save updates it instead of creating another, at the version its last
   * load or save here left (read from the server when there was none).
   */
  const openWith = (
    fields: { name: string; content: string },
    prompt?: Prompt,
  ) => {
    show(
      prompt
        ? { kind: 'edit', prompt }
        : { kind: 'new', copyOf: null, draft: false },
      fields,
    );
    setStatus('ready');
    if (!prompt) {
      setUpdatedAt(null);
      return;
    }
    if (versions.current.has(prompt.id)) {
      setUpdatedAt(versions.current.get(prompt.id) ?? null);
      return;
    }
    setUpdatedAt(null);
    const current = opening.current;
    fetchText(prompt.id)
      .then((loaded) => {
        versions.current.set(prompt.id, loaded.updated_at ?? null);
        if (opening.current === current)
          setUpdatedAt(loaded.updated_at ?? null);
      })
      // Unread, the save goes without a version, as it did before.
      .catch((error: unknown) => console.error(error));
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
  const saveBlocker: PromptSaveBlocker | null = !name.trim()
    ? 'name'
    : nameExists
      ? 'nameExists'
      : !content.trim()
        ? 'content'
        : templateBroken(content)
          ? 'template'
          : null;
  const canSave =
    !!target && !readOnly && status === 'ready' && saveBlocker === null;

  /**
   * Keep the version a save left, as its response gave it (a read after
   * the save could see someone else's later save, and saving at it would
   * overwrite theirs); a view still open on the prompt saves at it next.
   */
  const rememberVersion = (
    id: string,
    version: string | null,
    current: number,
  ) => {
    versions.current.set(id, version);
    const stillOpen = target?.kind === 'edit' && target.prompt.id === id;
    if (stillOpen && opening.current === current) setUpdatedAt(version);
  };

  /**
   * Saves the open prompt: creates a new one, or updates a saved one at the
   * version it opened with. A failure shows as a toast unless `quiet` (a
   * confirm dialog shows it itself).
   */
  const save = async ({ quiet = false } = {}): Promise<PromptSaveResult> => {
    if (!target || !canSave || saving) return 'failed';
    setSaving(true);
    const current = opening.current;
    let result: PromptSaveResult = 'failed';
    let savedId: string | null = null;
    let version: string | null = null;
    try {
      if (target.kind === 'new') {
        const response = await userService.createPrompt(
          { name, content },
          token,
        );
        if (response.ok) {
          const created = (await response.json()) as {
            id?: string;
            updated_at?: string | null;
          } | null;
          savedId = created?.id ?? null;
          version = created?.updated_at ?? null;
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
          const saved = (await response.json()) as {
            updated_at?: string | null;
          } | null;
          savedId = target.prompt.id;
          version = saved?.updated_at ?? null;
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
      rememberVersion(savedId, version, current);
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
    openWith,
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
    saveBlocker,
    saving,
    save,
  };
}

export type PromptDetail = ReturnType<typeof usePromptDetail>;
