import { createAsyncThunk, createSlice, PayloadAction } from '@reduxjs/toolkit';

import conversationService from '../../api/services/conversationService';
import { Query, Status } from '../../conversation/conversationModels';
import { WorkflowEdge, WorkflowNode } from '../types/workflow';

export interface WorkflowExecutionStep {
  nodeId: string;
  nodeType: string;
  nodeTitle: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  reasoning?: string;
  startedAt?: number;
  completedAt?: number;
  stateSnapshot?: Record<string, unknown>;
  output?: string;
  error?: string;
}

interface WorkflowData {
  name: string;
  description?: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

export interface WorkflowQuery extends Query {
  executionSteps?: WorkflowExecutionStep[];
}

export interface WorkflowPreviewState {
  queries: WorkflowQuery[];
  status: Status;
  executionSteps: WorkflowExecutionStep[];
  activeNodeId: string | null;
}

const initialState: WorkflowPreviewState = {
  queries: [],
  status: 'idle',
  executionSteps: [],
  activeNodeId: null,
};

let abortController: AbortController | null = null;

export function handleWorkflowPreviewAbort() {
  if (abortController) {
    abortController.abort();
    abortController = null;
  }
}

interface ThunkState {
  preference: {
    token: string | null;
  };
  workflowPreview: WorkflowPreviewState;
}

export const fetchWorkflowPreviewAnswer = createAsyncThunk<
  void,
  {
    question: string;
    workflowData: WorkflowData;
    indx?: number;
  },
  { state: ThunkState }
>(
  'workflowPreview/fetchAnswer',
  async ({ question, workflowData, indx }, { dispatch, getState }) => {
    if (abortController) abortController.abort();
    abortController = new AbortController();
    const { signal } = abortController;

    const state = getState();

    if (state.preference) {
      const payload = {
        question,
        workflow: workflowData,
        save_conversation: false,
      };

      await new Promise<void>((resolve, reject) => {
        conversationService
          .answerStream(payload, state.preference.token, signal)
          .then((response) => {
            if (!response.body) throw Error('No response body');

            let buffer = '';
            const reader = response.body.getReader();
            const decoder = new TextDecoder('utf-8');

            const processStream = ({
              done,
              value,
            }: ReadableStreamReadResult<Uint8Array>): Promise<void> | void => {
              if (done) {
                resolve();
                return;
              }

              buffer += decoder.decode(value, { stream: true });
              const lines = buffer.split('\n');
              buffer = lines.pop() || '';

              const currentState = getState();

              for (const line of lines) {
                if (line.startsWith('data:')) {
                  try {
                    const data = JSON.parse(line.slice(5));
                    const targetIndex =
                      indx ?? currentState.workflowPreview.queries.length - 1;

                    if (data.type === 'end') {
                      dispatch(workflowPreviewSlice.actions.setStatus('idle'));
                    } else if (data.type === 'thought') {
                      dispatch(
                        updateThought({
                          index: targetIndex,
                          query: { thought: data.thought },
                        }),
                      );
                    } else if (data.type === 'workflow_step') {
                      dispatch(
                        updateExecutionStep({
                          index: targetIndex,
                          step: {
                            nodeId: data.node_id,
                            nodeType: data.node_type,
                            nodeTitle: data.node_title,
                            status: data.status,
                            reasoning: data.reasoning,
                            stateSnapshot: data.state_snapshot,
                            output: data.output,
                            error: data.error,
                          },
                        }),
                      );
                      if (data.status === 'running') {
                        dispatch(setActiveNodeId(data.node_id));
                      }
                    } else if (data.type === 'source') {
                      dispatch(
                        updateStreamingSource({
                          index: targetIndex,
                          query: { sources: data.source ?? [] },
                        }),
                      );
                    } else if (data.type === 'tool_call') {
                      dispatch(
                        updateToolCall({
                          index: targetIndex,
                          tool_call: data.data,
                        }),
                      );
                    } else if (data.type === 'error') {
                      dispatch(
                        workflowPreviewSlice.actions.setStatus('failed'),
                      );
                      dispatch(
                        workflowPreviewSlice.actions.raiseError({
                          index: targetIndex,
                          message: data.error,
                        }),
                      );
                    } else if (data.type === 'structured_answer') {
                      dispatch(
                        updateStreamingQuery({
                          index: targetIndex,
                          query: {
                            response: data.answer,
                            structured: data.structured,
                            schema: data.schema,
                          },
                        }),
                      );
                    } else if (data.answer !== undefined) {
                      dispatch(
                        updateStreamingQuery({
                          index: targetIndex,
                          query: { response: data.answer },
                        }),
                      );
                    }
                  } catch {
                    /* empty */
                  }
                }
              }

              return reader.read().then(processStream);
            };

            reader.read().then(processStream).catch(reject);
          })
          .catch(reject);
      });
    }
  },
);

export const workflowPreviewSlice = createSlice({
  name: 'workflowPreview',
  initialState,
  reducers: {
    addQuery(state, action: PayloadAction<Query>) {
      state.queries.push(action.payload);
    },
    resendQuery(
      state,
      action: PayloadAction<{ index: number; prompt: string; query?: Query }>,
    ) {
      state.queries = [
        ...state.queries.slice(0, action.payload.index),
        { prompt: action.payload.prompt },
      ];
      state.executionSteps = [];
      state.activeNodeId = null;
    },
    updateStreamingQuery(
      state,
      action: PayloadAction<{
        index: number;
        query: Partial<Query>;
      }>,
    ) {
      const { index, query } = action.payload;
      if (state.status === 'idle') return;

      if (query.response !== undefined) {
        state.queries[index].response =
          (state.queries[index].response || '') + query.response;
      }

      if (query.structured !== undefined) {
        state.queries[index].structured = query.structured;
      }

      if (query.schema !== undefined) {
        state.queries[index].schema = query.schema;
      }
    },
    updateThought(
      state,
      action: PayloadAction<{
        index: number;
        query: Partial<Query>;
      }>,
    ) {
      const { index, query } = action.payload;
      if (query.thought !== undefined) {
        state.queries[index].thought =
          (state.queries[index].thought || '') + query.thought;
      }
    },
    updateStreamingSource(
      state,
      action: PayloadAction<{
        index: number;
        query: Partial<Query>;
      }>,
    ) {
      const { index, query } = action.payload;
      if (!state.queries[index].sources) {
        state.queries[index].sources = query?.sources;
      } else if (query.sources) {
        state.queries[index].sources!.push(...query.sources);
      }
    },
    updateToolCall(state, action) {
      const { index, tool_call } = action.payload;

      if (!state.queries[index].tool_calls) {
        state.queries[index].tool_calls = [];
      }

      const existingIndex = state.queries[index].tool_calls.findIndex(
        (call: { call_id: string }) => call.call_id === tool_call.call_id,
      );

      if (existingIndex !== -1) {
        const existingCall = state.queries[index].tool_calls[existingIndex];
        state.queries[index].tool_calls[existingIndex] = {
          ...existingCall,
          ...tool_call,
        };
      } else {
        state.queries[index].tool_calls.push(tool_call);
      }
    },
    updateQuery(
      state,
      action: PayloadAction<{ index: number; query: Partial<Query> }>,
    ) {
      const { index, query } = action.payload;
      state.queries[index] = {
        ...state.queries[index],
        ...query,
      };
    },
    updateExecutionStep(
      state,
      action: PayloadAction<{
        index: number;
        step: Partial<WorkflowExecutionStep> & {
          nodeId: string;
          nodeType: string;
          nodeTitle: string;
          status: WorkflowExecutionStep['status'];
        };
      }>,
    ) {
      const { index, step } = action.payload;

      if (!state.queries[index]) return;
      if (!state.queries[index].executionSteps) {
        state.queries[index].executionSteps = [];
      }

      const querySteps = state.queries[index].executionSteps!;
      const existingIndex = querySteps.findIndex((s) => s.nodeId === step.nodeId);

      const updatedStep: WorkflowExecutionStep = {
        nodeId: step.nodeId,
        nodeType: step.nodeType,
        nodeTitle: step.nodeTitle,
        status: step.status,
        reasoning: step.reasoning,
        stateSnapshot: step.stateSnapshot,
        output: step.output,
        error: step.error,
        startedAt: existingIndex !== -1 ? querySteps[existingIndex].startedAt : Date.now(),
        completedAt:
          step.status === 'completed' || step.status === 'failed'
            ? Date.now()
            : existingIndex !== -1
              ? querySteps[existingIndex].completedAt
              : undefined,
      };

      if (existingIndex !== -1) {
        updatedStep.stateSnapshot = step.stateSnapshot ?? querySteps[existingIndex].stateSnapshot;
        updatedStep.output = step.output ?? querySteps[existingIndex].output;
        updatedStep.error = step.error ?? querySteps[existingIndex].error;
        querySteps[existingIndex] = updatedStep;
      } else {
        querySteps.push(updatedStep);
      }

      const globalIndex = state.executionSteps.findIndex((s) => s.nodeId === step.nodeId);
      if (globalIndex !== -1) {
        state.executionSteps[globalIndex] = updatedStep;
      } else {
        state.executionSteps.push(updatedStep);
      }
    },
    setActiveNodeId(state, action: PayloadAction<string | null>) {
      state.activeNodeId = action.payload;
    },
    setStatus(state, action: PayloadAction<Status>) {
      state.status = action.payload;
    },
    raiseError(
      state,
      action: PayloadAction<{
        index: number;
        message: string;
      }>,
    ) {
      const { index, message } = action.payload;
      state.queries[index].error = message;
    },
    resetWorkflowPreview: (state) => {
      state.queries = initialState.queries;
      state.status = initialState.status;
      state.executionSteps = initialState.executionSteps;
      state.activeNodeId = initialState.activeNodeId;
      handleWorkflowPreviewAbort();
    },
    clearExecutionSteps: (state) => {
      state.executionSteps = [];
      state.activeNodeId = null;
    },
  },
  extraReducers(builder) {
    builder
      .addCase(fetchWorkflowPreviewAnswer.pending, (state) => {
        state.status = 'loading';
        state.executionSteps = [];
        state.activeNodeId = null;
      })
      .addCase(fetchWorkflowPreviewAnswer.rejected, (state, action) => {
        if (action.meta.aborted) {
          state.status = 'idle';
          return;
        }
        state.status = 'failed';
        if (state.queries.length > 0) {
          state.queries[state.queries.length - 1].error =
            'Something went wrong';
        }
      });
  },
});

interface RootStateWithWorkflowPreview {
  workflowPreview: WorkflowPreviewState;
}

export const selectWorkflowPreviewQueries = (
  state: RootStateWithWorkflowPreview,
) => state.workflowPreview.queries;
export const selectWorkflowPreviewStatus = (
  state: RootStateWithWorkflowPreview,
) => state.workflowPreview.status;
export const selectWorkflowExecutionSteps = (
  state: RootStateWithWorkflowPreview,
) => state.workflowPreview.executionSteps;
export const selectActiveNodeId = (state: RootStateWithWorkflowPreview) =>
  state.workflowPreview.activeNodeId;

export const {
  addQuery,
  updateQuery,
  resendQuery,
  updateStreamingQuery,
  updateThought,
  updateStreamingSource,
  updateToolCall,
  updateExecutionStep,
  setActiveNodeId,
  setStatus,
  raiseError,
  resetWorkflowPreview,
  clearExecutionSteps,
} = workflowPreviewSlice.actions;

export default workflowPreviewSlice.reducer;
