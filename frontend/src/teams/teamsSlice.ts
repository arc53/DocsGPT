import { createAsyncThunk, createSlice, PayloadAction } from '@reduxjs/toolkit';

import teamsService, { TeamRole } from '../api/services/teamsService';

export type Team = {
  id: string;
  name: string;
  slug: string;
  description?: string | null;
  owner_id: string;
  member_role?: TeamRole;
};

export type TeamsState = {
  teams: Team[];
  // Persisted UX-only selection (NEVER trusted for authorization — the
  // backend resolves team roles live from team_id in the URL path).
  currentTeamId: string | null;
  loading: boolean;
  error: string | null;
};

const STORED_CURRENT = localStorage.getItem('currentTeamId');

const initialState: TeamsState = {
  teams: [],
  currentTeamId: STORED_CURRENT || null,
  loading: false,
  error: null,
};

export const loadTeams = createAsyncThunk<Team[], { token: string | null }>(
  'teams/load',
  async ({ token }) => {
    const r = await teamsService.list(token);
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

export const deleteTeam = createAsyncThunk<
  string,
  { id: string; token: string | null }
>('teams/delete', async ({ id, token }) => {
  await teamsService.remove(id, token);
  return id;
});

const teamsSlice = createSlice({
  name: 'teams',
  initialState,
  reducers: {
    setCurrentTeam(state, action: PayloadAction<string | null>) {
      state.currentTeamId = action.payload;
      if (action.payload) localStorage.setItem('currentTeamId', action.payload);
      else localStorage.removeItem('currentTeamId');
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadTeams.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(loadTeams.fulfilled, (state, action) => {
        state.loading = false;
        state.teams = action.payload;
        // Drop a stale currentTeamId the user is no longer a member of.
        if (
          state.currentTeamId &&
          !action.payload.some((t) => t.id === state.currentTeamId)
        ) {
          state.currentTeamId = null;
          localStorage.removeItem('currentTeamId');
        }
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
        if (state.currentTeamId === action.payload) {
          state.currentTeamId = null;
          localStorage.removeItem('currentTeamId');
        }
      });
  },
});

export const { setCurrentTeam } = teamsSlice.actions;
export default teamsSlice.reducer;

export const selectTeams = (state: { teams: TeamsState }) => state.teams.teams;
export const selectCurrentTeamId = (state: { teams: TeamsState }) =>
  state.teams.currentTeamId;
export const selectTeamsLoading = (state: { teams: TeamsState }) =>
  state.teams.loading;
export const selectTeamsError = (state: { teams: TeamsState }) =>
  state.teams.error;
