import { useRef } from 'react';
import { useTranslation } from 'react-i18next';

import type { UndoneKind } from '../drafter/DrafterStepRow';
import type { ProposalReasonRow } from '../drafter/ProposalSummary';
import type { DraftedFields } from '../drafter/useDraftedFields';
import { joinList } from '../settings/insights/format';
import {
  AGENT_FIELD_LABEL_KEYS,
  AGENT_STEP_FIELDS,
  type AgentBuildStep,
  type AgentDraftField,
  type AgentDraftForm,
  type AgentProposal,
  type AppliedChange,
  editedSinceFields,
  parseAgentProposal,
  planAgentProposal,
  undoneKindOf,
} from './agentDraft';
import type { ToolSummary } from './types';

/** A drafted field's latest reason, with what it changed. */
export type BuildRow = ProposalReasonRow & { change?: AppliedChange };

type AgentProposalsOptions = {
  /** The form now. */
  form: AgentDraftForm;
  /** Its comparable values (agentDraftValues). */
  values: Record<AgentDraftField, unknown>;
  /** Tools a draft can name. */
  toolOptions: ToolSummary[];
  drafted: DraftedFields<AgentDraftField>;
  /** Write one drafted field. */
  writeField: (field: AgentDraftField, value: unknown) => void;
  /**
   * After a proposal filled the form, with the fields it changed: the host
   * opens a prompt it wrote and moves the build on.
   */
  onApplied: (
    proposal: AgentProposal,
    raw: object,
    changed: AgentDraftField[],
  ) => void;
};

/**
 * The agent drafter's proposals on the form: each one parsed once, applied
 * as unsaved edits (a field the user changed while the turn ran keeps their
 * value), every changed field marked Drafted with undo, and what each
 * changed kept for its summary in the drawer. All of it is keyed by the
 * session's proposal object.
 *
 * Args:
 *   options: The form, the drafted marks and how to write a field.
 *
 * Returns:
 *   `proposalOf` and `apply`; `markSent`, for the form each turn is sent
 *   with; per proposal `appliedFields`, `undoneRows`, `editedSince` and
 *   `announce`; `undoneKind` of a change; and the build's latest reason per
 *   field, as `stepRows` with `clearRows`.
 */
export function useAgentProposals({
  form,
  values,
  toolOptions,
  drafted,
  writeField,
  onApplied,
}: AgentProposalsOptions) {
  const { t } = useTranslation();
  // Each proposal read once: the drawer draws every one on each render.
  const parsedRef = useRef(new WeakMap<object, AgentProposal | null>());
  // The fields each proposal changed when it was applied, so its summary
  // gives reasons only for those and notes a later edit by hand.
  const appliedRef = useRef(new WeakMap<object, AppliedChange[]>());
  // The fields each proposal left as the user had changed them meanwhile,
  // with the value it would have set, for "You changed … in the form".
  const keptRef = useRef(new WeakMap<object, AppliedChange[]>());
  // The latest reason for each field a build drafted, with what it changed:
  // a finished step's folded line opens them.
  const rowsRef = useRef(new Map<AgentDraftField, BuildRow>());
  // The form as the latest turn was sent with, so a proposal leaves alone a
  // field the user changed while the turn ran.
  const sentRef = useRef<AgentDraftForm | null>(null);

  const keyOf = (raw: unknown): object | null =>
    raw && typeof raw === 'object' ? raw : null;

  const proposalOf = (raw: unknown): AgentProposal | null => {
    const key = keyOf(raw);
    if (!key) return null;
    const cached = parsedRef.current.get(key);
    if (cached !== undefined) return cached;
    const parsed = parseAgentProposal(raw);
    parsedRef.current.set(key, parsed);
    return parsed;
  };

  const appliedFields = (raw: unknown): AgentDraftField[] | undefined => {
    const key = keyOf(raw);
    return key
      ? appliedRef.current.get(key)?.map((change) => change.field)
      : undefined;
  };

  /**
   * Fill the form from a proposal, marking every field it changed. A field
   * the user changed while the turn ran keeps their value.
   */
  const apply = (raw: unknown) => {
    const proposal = proposalOf(raw);
    if (!proposal) return;
    const key = raw as object;
    const plan = planAgentProposal(
      proposal.fields,
      form,
      sentRef.current ?? form,
      toolOptions,
      drafted.undoValue,
    );
    keptRef.current.set(key, plan.kept);
    // A later proposal in the same turn takes this one's values as sent.
    sentRef.current = plan.sent;
    appliedRef.current.set(key, plan.applied);
    const changed = plan.changes.map((change) => change.field);
    plan.changes.forEach((change, index) => {
      writeField(change.field, change.next);
      drafted.mark(change.field, change.previous, plan.applied[index].applied);
    });
    proposal.reasons.forEach((reason) => {
      const field = reason.field as AgentDraftField;
      if (changed.includes(field))
        rowsRef.current.set(field, {
          key: field,
          label: t(AGENT_FIELD_LABEL_KEYS[field]),
          summary: reason.summary,
          change: plan.applied.find((change) => change.field === field),
        });
    });
    onApplied(proposal, key, changed);
  };

  const undoneKind = (change?: AppliedChange): UndoneKind | null =>
    undoneKindOf(change, values);

  /** A proposal's rows (by key) whose field the user undid since. */
  const undoneRows = (raw: unknown, rows: ProposalReasonRow[]) => {
    const undone = new Map<string, UndoneKind>();
    const key = keyOf(raw);
    (key ? (appliedRef.current.get(key) ?? []) : []).forEach((change) => {
      const kind = undoneKind(change);
      if (!kind) return;
      rows
        .filter((row) => row.key.startsWith(`${change.field}-`))
        .forEach((row) => undone.set(row.key, kind));
    });
    return undone;
  };

  /**
   * "You changed Name in the form.": fields the proposal set, edited since,
   * and those it left as the user changed them while the turn ran.
   */
  const editedSince = (raw: unknown) => {
    const key = keyOf(raw);
    const edited = editedSinceFields(
      (key && appliedRef.current.get(key)) || [],
      (key && keptRef.current.get(key)) || [],
      values,
    );
    return edited.length > 0
      ? t('drafter.agent.formEdited', {
          fields: joinList(
            edited.map((field) => t(AGENT_FIELD_LABEL_KEYS[field])),
          ),
          interpolation: { escapeValue: false },
        })
      : undefined;
  };

  /**
   * "Drafted 3 fields…" for a screen reader once a draft is applied; a field
   * undone since doesn't count.
   */
  const announce = (raw: unknown) => {
    const key = keyOf(raw);
    const count = (key ? (appliedRef.current.get(key) ?? []) : []).filter(
      (change) => !undoneKind(change),
    ).length;
    return count > 0 ? t('drafter.agent.draftedCount', { count }) : null;
  };

  /** A finished step's folded line opens the reasons for its fields. */
  const stepRows = (step: AgentBuildStep) =>
    AGENT_STEP_FIELDS[step].flatMap((field) => {
      const row = rowsRef.current.get(field);
      return row ? [row] : [];
    });

  return {
    proposalOf,
    apply,
    /** The form a turn was sent with, as its proposals apply onto. */
    markSent: (sent: AgentDraftForm) => {
      sentRef.current = sent;
    },
    appliedFields,
    undoneKind,
    undoneRows,
    editedSince,
    announce,
    stepRows,
    /** Forget the build's reasons (Start over, a publish). */
    clearRows: () => rowsRef.current.clear(),
  };
}
