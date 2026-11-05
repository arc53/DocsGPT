import { useCallback, useEffect, useRef, useState } from 'react';

import type { DrafterStarter } from '../drafter/starters';
import type { DrafterSession } from '../drafter/useDrafterSession';
import {
  AGENT_BUILD_STEPS,
  type AgentBuildStep,
  type AgentProposal,
} from './agentDraft';

/** Most of the user's earlier messages a request carries, and characters of one (agent_recipe.py). */
const MAX_EARLIER = 12;
const EARLIER_CHARS = 2000;

/**
 * `guided`: the step-by-step build of a new agent. `focused`: one step asked
 * for on a saved agent (Finish setup), with no tracker and no Next.
 */
type BuildMode = 'guided' | 'focused';

type BuildState = {
  mode: BuildMode | null;
  /** The step the conversation is on; null before the build and after it. */
  step: AgentBuildStep | null;
  /** The starting point the build began from, for every step's brief. */
  starter: DrafterStarter | null;
  /** The steps done, in build order. */
  finished: AgentBuildStep[];
  /** What the user wrote in the finished steps. */
  earlier: string[];
  /** How many steps the proposal that led here filled at once (0: one). */
  filledAtOnce: number;
  /** The current step's latest proposal: the steps it filled and the next. */
  ready: { steps: AgentBuildStep[]; next: AgentBuildStep | null } | null;
  /** The latest proposal changed nothing (an approval): Next runs on its own. */
  approved: boolean;
};

const IDLE: BuildState = {
  mode: null,
  step: null,
  starter: null,
  finished: [],
  earlier: [],
  filledAtOnce: 0,
  ready: null,
  approved: false,
};

export type AgentBuildOptions = {
  session: DrafterSession;
  /** Steps with nothing to set for this caller: passed over, out of the count. */
  skipped: AgentBuildStep[];
  /** The hidden message that starts a step ("Continue with Knowledge and tools."). */
  continueText: (step: AgentBuildStep) => string;
  /** The drawer's message once every step is done. */
  doneText: string;
};

export type AgentBuild = {
  /** The step the recipe is told about; null in improve mode. */
  step: AgentBuildStep | null;
  /** A guided build is under way (Resume, the tracker, Next). */
  guided: boolean;
  /** Every step of the guided build is done. */
  done: boolean;
  finished: AgentBuildStep[];
  skipped: AgentBuildStep[];
  /** Steps the build counts (the skipped ones left out). */
  total: number;
  /** The current step's place among them, from 1. */
  number: number;
  filledAtOnce: number;
  /** A proposal in this step waits for Next. */
  ready: boolean;
  /** The latest proposal filled more than this step. */
  filledAhead: boolean;
  /** The latest proposal was an approval: Next is on its way. */
  approved: boolean;
  /** Where Next goes; null when it finishes the build. */
  nextStep: AgentBuildStep | null;
  /** Start the guided build at its first step, from a starting point or none. */
  start: (starter?: DrafterStarter) => void;
  /** Ask for one step on a saved agent, for the rest of the conversation. */
  focus: (step: AgentBuildStep) => void;
  /** Record a proposal the session applied. */
  onProposal: (proposal: AgentProposal) => void;
  /**
   * Fold the step (and those its proposal filled), keep what the user wrote
   * in it, start the conversation over and run the next step, or finish.
   */
  next: () => void;
  /** Forget the build (after Publish). */
  reset: () => void;
  /** What the recipe's context carries: the step, the earlier words and the starting point. */
  context: () => {
    step: AgentBuildStep | null;
    earlier: string[];
    starter: DrafterStarter | null;
  };
};

/** The first step after `from` that is neither done nor skipped. */
function stepAfter(
  from: AgentBuildStep | null,
  done: AgentBuildStep[],
  skipped: AgentBuildStep[],
): AgentBuildStep | null {
  const start = from ? AGENT_BUILD_STEPS.indexOf(from) + 1 : 0;
  return (
    AGENT_BUILD_STEPS.slice(start).find(
      (step) => !done.includes(step) && !skipped.includes(step),
    ) ?? null
  );
}

/** Where Next goes from this state. */
function nextOf(state: BuildState, skipped: AgentBuildStep[]) {
  if (!state.step) return null;
  const filled = [...state.finished, state.step, ...(state.ready?.steps ?? [])];
  const proposed = state.ready?.next;
  if (proposed && !filled.includes(proposed) && !skipped.includes(proposed))
    return proposed;
  return stepAfter(state.step, filled, skipped);
}

/**
 * The guided build of a new agent ("Draft with DocsGPT" on an empty form):
 * four steps (basics, knowledge and tools, prompt and starters, limits and
 * safety), each one conversation. A proposal readies the step's Next; an
 * empty one (the user approved) runs Next once its turn ends. Next folds the
 * step and those its proposal filled ahead, keeps the user's words for
 * `earlier`, starts the session over and opens the next step with a hidden
 * message, or finishes. Steps with nothing to set are passed over and
 * leave the count. A build begun from a starting point carries it to every
 * step, where the recipe adds that kind of agent's brief. The state is
 * mirrored in a ref, so the context of a message sent right after a change
 * already reads it.
 *
 * Args:
 *   options: The session, the skipped steps and the client's messages.
 *
 * Returns:
 *   The build's state and actions.
 */
export function useAgentBuild({
  session,
  skipped,
  continueText,
  doneText,
}: AgentBuildOptions): AgentBuild {
  const [state, setRendered] = useState<BuildState>(IDLE);
  const stateRef = useRef(state);
  const setState = useCallback((next: BuildState) => {
    stateRef.current = next;
    setRendered(next);
  }, []);
  const latest = useRef({ session, skipped, continueText, doneText });
  latest.current = { session, skipped, continueText, doneText };

  const start = useCallback(
    (starter?: DrafterStarter) => {
      if (stateRef.current.mode) return;
      setState({
        ...IDLE,
        mode: 'guided',
        step: stepAfter(null, [], latest.current.skipped),
        starter: starter ?? null,
      });
    },
    [setState],
  );

  const focus = useCallback(
    (step: AgentBuildStep) => {
      if (stateRef.current.mode === 'guided' && !isDone(stateRef.current))
        return;
      setState({ ...IDLE, mode: 'focused', step });
    },
    [setState],
  );

  const onProposal = useCallback(
    (proposal: AgentProposal) => {
      const current = stateRef.current;
      if (current.mode !== 'guided' || !current.step) return;
      setState({
        ...current,
        ready: {
          steps: proposal.steps.length ? proposal.steps : [current.step],
          next: proposal.next_step,
        },
        approved: Object.keys(proposal.fields).length === 0,
      });
    },
    [setState],
  );

  const next = useCallback(() => {
    const current = stateRef.current;
    if (current.mode !== 'guided' || !current.step) return;
    const { session, skipped, continueText, doneText } = latest.current;
    const target = nextOf(current, skipped);
    const filled = new Set([
      ...current.finished,
      current.step,
      ...(current.ready?.steps ?? []),
    ]);
    const steps = current.ready?.steps ?? [current.step];
    setState({
      ...current,
      step: target,
      finished: AGENT_BUILD_STEPS.filter((step) => filled.has(step)),
      earlier: [
        ...current.earlier,
        ...session.userTexts().map((text) => text.slice(0, EARLIER_CHARS)),
      ].slice(-MAX_EARLIER),
      filledAtOnce: steps.length > 1 ? steps.length : 0,
      ready: null,
      approved: false,
    });
    session.reset();
    if (target) session.send(continueText(target), { hidden: true });
    else session.addMessage(doneText);
  }, [setState]);

  const reset = useCallback(() => setState(IDLE), [setState]);

  const context = useCallback(
    () => ({
      step: stateRef.current.step,
      earlier: stateRef.current.earlier,
      starter: stateRef.current.starter,
    }),
    [],
  );

  // An approval moves on once its turn is over.
  const { streaming } = session;
  useEffect(() => {
    if (!streaming && state.approved) next();
  }, [streaming, state.approved, next]);

  const guided = state.mode === 'guided';
  const counted = AGENT_BUILD_STEPS.filter((step) => !skipped.includes(step));
  return {
    step: state.step,
    guided,
    done: isDone(state),
    finished: state.finished,
    skipped,
    total: counted.length,
    number: state.step ? counted.indexOf(state.step) + 1 : counted.length,
    filledAtOnce: state.filledAtOnce,
    ready: guided && !!state.ready && !state.approved,
    filledAhead: (state.ready?.steps.length ?? 0) > 1,
    approved: state.approved,
    nextStep: nextOf(state, skipped),
    start,
    focus,
    onProposal,
    next,
    reset,
    context,
  };
}

function isDone(state: BuildState): boolean {
  return state.mode === 'guided' && state.step === null;
}
