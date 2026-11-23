import {
  createAsyncThunk,
  createSlice,
  miniSerializeError,
  type SerializedError,
} from '@reduxjs/toolkit';

import teamsService, {
  LegacyTeamRole,
  OutsidePolicy,
  OutsidePolicyFields,
  OutsidePolicyResult,
  TeamRole,
} from '../api/services/teamsService';
import { outsidePolicyChanged } from '../workspace/workspaceSlice';

/** A team row; `outside_policy` is who may take its items outside. */
export type Team = OutsidePolicyFields & {
  id: string;
  name: string;
  slug: string;
  description?: string | null;
  owner_id: string;
  // Whether the caller owns the team (only the owner may delete it). Newer
  // servers send it; older ones only `owner_id`, compared to the caller's sub.
  is_owner?: boolean;
  /** The caller's role; null for a non-member (an instance admin). */
  role?: TeamRole | null;
  /** The caller's role in the old names. */
  member_role?: LegacyTeamRole;
  // Annotations from the list endpoint for the teams grid cards.
  member_count?: number;
  shared_count?: number;
};

// The team the app is in lives in the `workspace` slice.
export type TeamsState = {
  teams: Team[];
  loading: boolean;
  error: string | null;
};

const initialState: TeamsState = {
  teams: [],
  loading: false,
  error: null,
};

export const loadTeams = createAsyncThunk<Team[], { token: string | null }>(
  'teams/load',
  async ({ token }) => {
    // teamsService rejects on a non-2xx, so a failed load lands in .rejected.
    const r = await teamsService.list(token);
    if (r?.success === false) {
      throw new Error(r?.message ?? 'Failed to load teams');
    }
    return (r?.teams as Team[]) ?? [];
  },
);

export const createTeam = createAsyncThunk<
  Team,
  { name: string; description?: string; token: string | null }
>('teams/create', async ({ name, description, token }) => {
  const r = await teamsService.create({ name, description }, token);
  // apiClient resolves on any HTTP status, so a backend error parses to
  // { success:false, message }. Reject so .unwrap() throws (modal keeps its
  // error open) and we never push an undefined team into the list.
  if (!r || r.success === false || !r.team) {
    throw new Error(r?.message ?? 'Failed to create team');
  }
  return r.team as Team;
});

/** A refused delete: the error's fields, and what the team still owns. */
export type DeleteTeamError = SerializedError & {
  counts?: Record<string, number>;
};

export const deleteTeam = createAsyncThunk<
  string,
  { id: string; token: string | null },
  { serializedErrorType: DeleteTeamError }
>(
  'teams/delete',
  async ({ id, token }) => {
    // A non-2xx (e.g. 403 for a non-owner) rejects in teamsService, so the
    // team stays in the list; a 2xx that still says success:false rejects too.
    const r = await teamsService.remove(id, token);
    if (r?.success === false) {
      throw new Error(r?.message ?? 'Failed to delete team');
    }
    return id;
  },
  {
    // A team that still owns items is refused with their counts; keep them
    // (and the refusal's code) for the caller of `unwrap`.
    serializeError: (error): DeleteTeamError => {
      // A `TeamsApiError` carries the answer's body.
      const counts = (error as { body?: { counts?: unknown } } | null)?.body
        ?.counts;
      return {
        ...miniSerializeError(error),
        ...(counts && typeof counts === 'object'
          ? { counts: counts as Record<string, number> }
          : {}),
      };
    },
  },
);

/**
 * Changes who may take a team's items outside. Once the server agrees, the
 * team's row here and its workspace row follow; a refusal (an Admin
 * unlocking: `policy_owner_only`) rejects with its code for
 * `teamErrorMessage`, and nothing changes.
 */
export const setTeamOutsidePolicy = createAsyncThunk<
  OutsidePolicyResult,
  { teamId: string; policy: OutsidePolicy; token: string | null }
>('teams/setOutsidePolicy', async ({ teamId, policy, token }, { dispatch }) => {
  const result = await teamsService.setOutsidePolicy(teamId, policy, token);
  dispatch(
    outsidePolicyChanged({
      teamId,
      outside_policy: result.outside_policy,
      can_set_outside_policy: result.can_set_outside_policy,
    }),
  );
  return result;
});

const teamsSlice = createSlice({
  name: 'teams',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(loadTeams.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(loadTeams.fulfilled, (state, action) => {
        state.loading = false;
        state.teams = action.payload;
      })
      .addCase(loadTeams.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to load teams';
      })
      .addCase(createTeam.fulfilled, (state, action) => {
        state.teams.push(action.payload);
      })
      .addCase(deleteTeam.fulfilled, (state, action) => {
        state.teams = state.teams.filter((t) => t.id !== action.payload);
      })
      .addCase(outsidePolicyChanged, (state, action) => {
        const team = state.teams.find((t) => t.id === action.payload.teamId);
        if (!team) return;
        team.outside_policy = action.payload.outside_policy;
        team.can_set_outside_policy = action.payload.can_set_outside_policy;
      });
  },
});

export default teamsSlice.reducer;

export const selectTeams = (state: { teams: TeamsState }) => state.teams.teams;
export const selectTeamsLoading = (state: { teams: TeamsState }) =>
  state.teams.loading;
export const selectTeamsError = (state: { teams: TeamsState }) =>
  state.teams.error;
