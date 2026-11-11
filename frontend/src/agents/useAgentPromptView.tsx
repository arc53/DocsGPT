import {
  type ComponentProps,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useLocation, useNavigate } from 'react-router-dom';

import { MetaLine } from '@/components/ui/meta-line';

import userService from '../api/services/userService';
import type { PromptEdit } from '../drafter/promptDraft';
import {
  type DraftedFields,
  useDraftedFields,
} from '../drafter/useDraftedFields';
import { usePromptReview } from '../drafter/usePromptReview';
import { WandButton } from '../drafter/WandButton';
import type { Prompt } from '../models/misc';
import { selectToken, setPrompts } from '../preferences/preferenceSlice';
import { PromptView } from '../prompts/PromptView';
import {
  PromptConflictNotice,
  PromptLeaveDialog,
  PromptSaveButton,
  promptSaveDisabled,
} from '../prompts/PromptViewChrome';
import { usePromptDetail } from '../prompts/usePromptDetail';
import { can } from '../utils/accessUtils';
import type {
  AgentDraftField,
  AgentDraftForm,
  PromptDraft,
} from './agentDraft';
import { cleanStarters } from './starters';

type AgentPromptViewOptions = {
  /** The listed prompts (the pickers' list). */
  prompts: Prompt[];
  /** The form's Prompt picker: the view hands focus back to it. */
  pickerId: string;
  /** The form now. */
  getForm: () => AgentDraftForm;
  /** The form's Drafted marks: Use this prompt marks the prompt it sets. */
  drafted: DraftedFields<AgentDraftField>;
  /** Write one form field (the prompt a save sets). */
  writeField: (field: AgentDraftField, value: unknown) => void;
  /** Add a message of the client's to the drawer. */
  addMessage: (text: string) => void;
  /** Open the drawer (improving a copy of a prompt). */
  openDrafter: () => void;
};

/** What the view's crumb row needs from the form when it draws. */
type PromptViewRender = {
  /** The crumb back to the form: the agent's name. */
  parentLabel: string;
  /** A drafter turn runs: the text is locked and Save waits. */
  streaming: boolean;
  /** The toolbar's wand, with its toggle; null while the drafter is off. */
  wand: {
    props: Omit<ComponentProps<typeof WandButton>, 'onClick'>;
    toggle: () => void;
  } | null;
};

/**
 * The agent form's prompt view (decision 64): a prompt shown in place of
 * the form, the form kept as it is under it. The drafter opens a prompt it
 * wrote there (`drafter`: Use this prompt saves it and sets it on the
 * agent), and its changes to a saved prompt as a review; the picker's Add
 * prompt and each row's Edit or View open one too (`picker`: Save). A
 * history entry makes browser Back return to the form.
 *
 * Args:
 *   options: The listed prompts, the form's picker, and what the view
 *     reads and writes on the form and the drawer.
 *
 * Returns:
 *   Whether it is `open` (and `dirty`); the prompt the drafter reads
 *   (`draft`) and the one it wrote that waits unused (`parked`); `used`
 *   after Use this prompt; the `review` of changes and whether changes
 *   wait for the text (`editsPending`); what the drafter does with it
 *   (`markSent`, `showWritten`, `showEdits`, `fitting`, `dropDraft`,
 *   `reopenDraft`, `forget`); the picker's `openPicker` and `addPicker`;
 *   `leave`; and `render` for the view with its leave `dialog`.
 */
export function useAgentPromptView({
  prompts,
  pickerId,
  getForm,
  drafted,
  writeField,
  addMessage,
  openDrafter,
}: AgentPromptViewOptions) {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const token = useSelector(selectToken);

  /** Load the prompts the pickers read again (after a prompt is saved). */
  const reloadPrompts = () =>
    userService
      .getPrompts(token)
      .then((response: Response) => (response.ok ? response.json() : null))
      .then((list: Prompt[] | null) => {
        if (Array.isArray(list)) dispatch(setPrompts(list));
      })
      .catch((error: unknown) => console.error(error));

  const location = useLocation();
  const [promptOrigin, setPromptOrigin] = useState<'drafter' | 'picker'>(
    'picker',
  );
  // The prompt the drafter wrote and the user hasn't used or turned down
  // yet: kept while the view is closed, so the drawer can open it again.
  const [promptDraft, setPromptDraft] = useState<PromptDraft | null>(null);
  // The prompt Use this prompt saved, with its text: a later draft while the
  // agent still uses it updates it instead of creating another.
  const usedPromptRef = useRef<{ prompt: Prompt; content: string } | null>(
    null,
  );
  // Use this prompt went through and nothing was sent since: the drawer
  // ends that turn with what it set and the step's Next.
  const [promptUsed, setPromptUsed] = useState(false);
  // Leaving the picker's view with unsaved text asks first.
  const [leavingPrompt, setLeavingPrompt] = useState(false);
  const promptDetail = usePromptDetail({
    prompts,
    onSaved: (saved) => handlePromptSaved(saved),
  });
  const promptViewOpen = promptDetail.target !== null;
  const promptValues = useMemo(
    () => ({ name: promptDetail.name, content: promptDetail.content }),
    [promptDetail.name, promptDetail.content],
  );
  const { setName: setPromptName, setContent: setPromptContent } = promptDetail;
  const promptDrafted = useDraftedFields<'name' | 'content'>(
    promptValues,
    (field, previous) =>
      (field === 'name' ? setPromptName : setPromptContent)(
        typeof previous === 'string' ? previous : '',
      ),
  );
  // The drafter's changes to a saved prompt, under review in the view.
  const promptReview = usePromptReview(setPromptContent, promptDrafted);
  // The prompt text the drafter reads: the open view's once loaded, with the
  // id of the saved prompt it shows (opened from a picker row, it needn't be
  // the agent's), else the drafter's unused prompt.
  const viewTargetId =
    promptDetail.target?.kind === 'edit' ? promptDetail.target.prompt.id : null;
  const draftOfPrompt: PromptDraft | null =
    promptViewOpen && promptDetail.status === 'ready'
      ? viewTargetId
        ? { ...promptValues, id: viewTargetId }
        : promptValues
      : promptDraft;

  const viewInHistory =
    (location.state as { promptView?: boolean } | null)?.promptView === true;
  // Back onto the view's entry with no view open (the page was left through
  // the sidebar while it was): the entry goes too, so one more Back leaves
  // the form rather than two.
  useEffect(() => {
    if (viewInHistory && !promptViewOpen) navigate(-1);
    // Only as the form mounts.
  }, []);
  // Each opening pushes the history entry Back pops, unless one is there.
  useEffect(() => {
    if (!promptViewOpen || viewInHistory) return;
    const state =
      location.state && typeof location.state === 'object'
        ? location.state
        : {};
    navigate(
      {
        pathname: location.pathname,
        search: location.search,
        hash: location.hash,
      },
      { state: { ...state, promptView: true } },
    );
  }, [promptDetail.key]);

  /** Close the view and drop its history entry. */
  const closePromptView = () => {
    promptReview.clear();
    promptDetail.close();
    if (viewInHistory) navigate(-1);
    // Back on the form where the prompt is picked, with focus there when
    // the view's button that closed it (Use this prompt) took it along.
    requestAnimationFrame(() => {
      const picker = document.getElementById(pickerId);
      picker?.scrollIntoView?.({ block: 'center' });
      const active = document.activeElement;
      if (!active || active === document.body || !active.isConnected)
        picker?.focus({ preventScroll: true });
    });
  };

  /**
   * Back to the form (the crumb, or browser Back with `popped`): the
   * drafter's prompt stays in the step unsaved; unsaved text of the
   * picker's asks first. Returns whether the view closed (false while it
   * asks).
   */
  const leavePromptView = (popped = false): boolean => {
    if (promptOrigin === 'drafter') {
      // An update of the prompt Use this prompt saved keeps its id.
      setPromptDraft(draftOfPrompt ?? promptValues);
      closePromptView();
      return true;
    }
    if (promptDetail.dirty) {
      // Browser Back already left the entry: put it back while asking, with
      // the rest of what the entry held.
      if (popped) {
        const state =
          location.state && typeof location.state === 'object'
            ? location.state
            : {};
        navigate(
          {
            pathname: location.pathname,
            search: location.search,
            hash: location.hash,
          },
          { state: { ...state, promptView: true } },
        );
      }
      setLeavingPrompt(true);
      return false;
    }
    closePromptView();
    return true;
  };

  const wasInHistoryRef = useRef(viewInHistory);
  useEffect(() => {
    const was = wasInHistoryRef.current;
    wasInHistoryRef.current = viewInHistory;
    if (was && !viewInHistory && promptViewOpen) leavePromptView(true);
  }, [viewInHistory]);

  /** Open a prompt from the picker: to edit, or to read when the role can't. */
  const openPickerPrompt = (prompt: Prompt) => {
    setPromptOrigin('picker');
    promptDrafted.clear();
    promptDetail.open(prompt);
  };
  /** The picker's Add prompt. */
  const addPickerPrompt = () => {
    setPromptOrigin('picker');
    promptDrafted.clear();
    promptDetail.add();
  };
  /** A copy of a prompt the caller can't change, with the drawer open on it. */
  const improvePromptCopy = (prompt: Prompt) => {
    setPromptOrigin('picker');
    promptDrafted.clear();
    openDrafter();
    void promptDetail.duplicate(prompt, { draft: true });
  };

  /**
   * Which prompt the open view shows, so a turn's answer can tell it is
   * still the one the turn read: the drafter's own (new, or the update of
   * the prompt it used), a saved prompt, or one opening of a new prompt.
   */
  const promptViewIdentity = (): string | null => {
    if (!promptDetail.target) return null;
    if (promptOrigin === 'drafter') return 'drafter';
    return promptDetail.target.kind === 'edit'
      ? `edit:${promptDetail.target.prompt.id}`
      : `new:${promptDetail.key}`;
  };
  // The prompt the running turn read (its prompt_draft): the open view's
  // once loaded, else the drafter's own.
  const sentPromptRef = useRef<string | null>('drafter');

  /**
   * Put a prompt the drafter wrote in the view: into the open one when it
   * is still the prompt the turn read (a saved prompt opened from the
   * picker keeps its name), or a new view, which updates the prompt this
   * conversation already used while the agent still has it. A prompt the
   * caller can only read is never written into (it has no Save): the new
   * view takes its place. Another prompt opened since, with unsaved text,
   * stays: the written one waits in the step. Each changed field is marked
   * Drafted with undo.
   */
  const showWrittenPrompt = (written: PromptDraft) => {
    if (
      promptViewOpen &&
      !promptDetail.readOnly &&
      promptViewIdentity() === sentPromptRef.current
    ) {
      const keepsName =
        promptOrigin === 'picker' && promptDetail.target?.kind === 'edit';
      if (!keepsName && written.name && written.name !== promptDetail.name) {
        promptDrafted.mark('name', promptDetail.name, written.name);
        setPromptName(written.name);
      }
      if (written.content !== promptDetail.content) {
        promptDrafted.mark('content', promptDetail.content, written.content);
        setPromptContent(written.content);
      }
      return;
    }
    if (promptViewOpen && promptOrigin === 'picker' && promptDetail.dirty) {
      setPromptDraft(written);
      return;
    }
    const used = usedPromptRef.current;
    const updates = used && getForm().prompt === used.prompt.id ? used : null;
    const previous =
      promptDraft ??
      (updates
        ? { name: updates.prompt.name, content: updates.content }
        : { name: '', content: '' });
    setPromptOrigin('drafter');
    promptDetail.openWith(written, updates?.prompt);
    if (written.name !== previous.name)
      promptDrafted.mark('name', previous.name, written.name);
    if (written.content !== previous.content)
      promptDrafted.mark('content', previous.content, written.content);
    setPromptDraft(written);
  };

  // Changes to a saved prompt wait for its text when the view loads it
  // (`raw`: the proposal they came in).
  const [pendingEdits, setPendingEdits] = useState<{
    raw: object;
    id: string;
    edits: PromptEdit[];
  } | null>(null);
  // How many of a proposal's changes fit the text, for its summary.
  const fittingRef = useRef(new WeakMap<object, number>());
  /**
   * Review the drafter's changes on the open prompt's text, those that fit
   * it as the server reads it; the characters outside a change stay.
   */
  const reviewPromptEdits = (raw: object, edits: PromptEdit[]) => {
    const fitting = promptReview.start(edits, promptDetail.content);
    fittingRef.current.set(raw, fitting);
    if (fitting === 0) addMessage(t('drafter.agent.prompt.editsStale'));
  };
  // They belong to that opening: a view closed or showing another prompt
  // drops them, so opening the prompt later shows no stale review. A load
  // error keeps them for the view's Retry.
  useEffect(() => {
    if (!pendingEdits) return;
    if (viewTargetId !== pendingEdits.id) setPendingEdits(null);
    else if (promptDetail.status === 'ready') {
      setPendingEdits(null);
      reviewPromptEdits(pendingEdits.raw, pendingEdits.edits);
    }
  }, [pendingEdits, promptDetail.status, promptDetail.key, viewTargetId]);

  /**
   * Show the drafter's changes to the agent's own saved prompt: in its view
   * when that is open, else it opens (loading its saved text and version)
   * and the review starts once the text is in. The drawer stays the
   * agent's; nothing is saved until the view's Save.
   */
  const showPromptEdits = (raw: object, id: string, edits: PromptEdit[]) => {
    if (viewTargetId === id && promptDetail.status === 'ready') {
      reviewPromptEdits(raw, edits);
      return;
    }
    const prompt = prompts.find((item) => item.id === id);
    if (!prompt) {
      addMessage(t('drafter.agent.prompt.editsStale'));
      return;
    }
    setPendingEdits({ raw, id, edits });
    setPromptOrigin('picker');
    promptDrafted.clear();
    promptDetail.open(prompt);
  };

  /** Turn the drafter's unused prompt down: the agent keeps its prompt. */
  const dropPromptDraft = () => {
    if (promptViewOpen && promptOrigin === 'drafter') closePromptView();
    setPromptDraft(null);
    promptDrafted.clear();
  };

  /** Open the drafter's unused prompt again (the drawer's Open prompt). */
  const reopenPromptDraft = () => {
    if (!promptDraft) return;
    const used = usedPromptRef.current;
    setPromptOrigin('drafter');
    promptDetail.openWith(
      promptDraft,
      used && getForm().prompt === used.prompt.id ? used.prompt : undefined,
    );
  };

  /**
   * A save in the view went through: the pickers' list has it at once.
   * The drafter's prompt is set on the agent (marked Drafted, undo puts the
   * old one back) and the drawer says so; a prompt added from the picker is
   * picked.
   */
  const handlePromptSaved = ({ id, name }: { id: string; name: string }) => {
    const target = promptDetail.target;
    // A copy kept after a conflict stands in for the agent's prompt it
    // copied, as a new prompt does.
    const created =
      target?.kind === 'new' ||
      (target?.kind === 'edit' &&
        target.prompt.id !== id &&
        getForm().prompt === target.prompt.id);
    const listed = prompts.find((prompt) => prompt.id === id);
    dispatch(
      setPrompts(
        listed
          ? prompts.map((prompt) =>
              prompt.id === id ? { ...prompt, name } : prompt,
            )
          : [...prompts, { id, name, type: 'private' }],
      ),
    );
    void reloadPrompts();
    if (promptOrigin === 'drafter') {
      usedPromptRef.current = {
        prompt: listed ? { ...listed, name } : { id, name, type: 'private' },
        content: promptDetail.content,
      };
      const previous = getForm().prompt;
      if (previous !== id) {
        writeField('prompt', id);
        drafted.mark('prompt', previous, id);
      }
      setPromptDraft(null);
      setPromptUsed(true);
      const starters = drafted.isDrafted('starters')
        ? cleanStarters(getForm().starters).length
        : 0;
      addMessage(
        starters > 0
          ? t('drafter.agent.prompt.saved', { count: starters })
          : t('drafter.agent.prompt.savedOnly'),
      );
    } else if (created) writeField('prompt', id);
    promptDrafted.clear();
    closePromptView();
  };

  const view = promptDetail.target;
  const saveDisabled = (streaming: boolean) =>
    promptSaveDisabled(promptDetail, streaming || promptReview.review !== null);

  /** The view in place of the form; null while none is open. */
  const render = ({ parentLabel, streaming, wand }: PromptViewRender) => {
    if (!view) return null;
    // The open prompt as the list has it (a built-in says so in the byline).
    const saved = view.kind === 'edit' ? view.prompt : null;
    const builtIn = saved?.type === 'public';
    // A prompt the caller can't change is improved as a copy, when they may
    // copy it.
    const improvable =
      !promptDetail.readOnly || (!!saved && can(saved, 'duplicate'));
    const byline =
      promptOrigin === 'picker'
        ? builtIn
          ? t('modals.prompts.viewDescription')
          : view.kind === 'new' && view.copyOf
            ? t('modals.prompts.duplicateDescription', {
                name: view.copyOf,
                interpolation: { escapeValue: false },
              })
            : null
        : null;
    const disabled = saveDisabled(streaming);
    return (
      <PromptView
        parent={{ label: parentLabel, onClick: () => leavePromptView() }}
        label={
          saved
            ? saved.name
            : promptOrigin === 'drafter'
              ? t('drafter.agent.prompt.newPrompt')
              : view.kind === 'new' && view.copyOf
                ? t('modals.prompts.duplicatePrompt')
                : t('modals.prompts.addPrompt')
        }
        actions={
          <>
            {wand && improvable && (
              <WandButton
                {...wand.props}
                open={promptDetail.readOnly ? undefined : wand.props.open}
                onClick={() =>
                  // A prompt the caller can't change is improved as a copy.
                  promptDetail.readOnly && saved
                    ? improvePromptCopy(saved)
                    : wand.toggle()
                }
              />
            )}
            {!promptDetail.readOnly && (
              <PromptSaveButton
                detail={promptDetail}
                disabled={disabled}
                label={
                  promptOrigin === 'drafter'
                    ? t('drafter.agent.prompt.use')
                    : undefined
                }
              />
            )}
          </>
        }
        byline={byline ? <MetaLine>{byline}</MetaLine> : null}
        loading={promptDetail.status === 'loading'}
        onRetry={
          promptDetail.status === 'error' ? promptDetail.retry : undefined
        }
        notice={
          <PromptConflictNotice detail={promptDetail} disabled={disabled} />
        }
        idPrefix="agent-prompt"
        name={promptDetail.name}
        setName={setPromptName}
        content={promptDetail.content}
        setContent={setPromptContent}
        isReadOnly={promptDetail.readOnly}
        showViewOnlyNotice={promptDetail.readOnly && !builtIn}
        review={promptReview.review}
        onDecide={promptReview.decide}
        draftedName={{
          drafted: promptDrafted.isDrafted('name'),
          onUndo: () => promptDrafted.undo('name'),
        }}
        draftedContent={{
          drafted: promptDrafted.isDrafted('content'),
          onUndo: () => promptDrafted.undo('content'),
        }}
        nameError={
          promptDetail.nameExists && promptDetail.name
            ? t('modals.prompts.nameExists')
            : undefined
        }
        locked={streaming}
      />
    );
  };

  return {
    open: promptViewOpen,
    /** The open view has unsaved text. */
    dirty: promptViewOpen && promptDetail.dirty,
    /** The prompt the drafter reads (the open view's, else the unused one). */
    draft: draftOfPrompt,
    /** The prompt the drafter wrote that waits unused, if any. */
    parked: promptDraft,
    used: promptUsed,
    setUsed: setPromptUsed,
    review: promptReview,
    /** Changes to a saved prompt wait for its text to load. */
    editsPending: pendingEdits !== null,
    /**
     * A turn is sent: an open review ends with the choices so far, and the
     * turn's answer goes to the prompt it read.
     */
    markSent: () => {
      promptReview.finish(promptDetail.content);
      sentPromptRef.current =
        promptViewOpen && promptDetail.status === 'ready'
          ? promptViewIdentity()
          : 'drafter';
    },
    showWritten: showWrittenPrompt,
    showEdits: showPromptEdits,
    /** How many of a proposal's changes fit the text, once reviewed. */
    fitting: (raw: unknown) =>
      raw && typeof raw === 'object' ? fittingRef.current.get(raw) : undefined,
    dropDraft: dropPromptDraft,
    reopenDraft: reopenPromptDraft,
    /** Forget what the drafter wrote and used (a publish ends the session). */
    forget: () => {
      setPromptDraft(null);
      setPromptUsed(false);
      usedPromptRef.current = null;
      promptDrafted.clear();
    },
    openPicker: openPickerPrompt,
    addPicker: addPickerPrompt,
    leave: leavePromptView,
    render,
    /** Leaving the picker's view with unsaved text asks first. */
    dialog: leavingPrompt ? (
      <PromptLeaveDialog
        detail={promptDetail}
        reviewing={promptReview.review !== null}
        onClose={() => setLeavingPrompt(false)}
        onLeave={() => {
          promptDrafted.clear();
          closePromptView();
        }}
      />
    ) : null,
  };
}
