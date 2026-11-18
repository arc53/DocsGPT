/**
 * Routes of the Activity section: what runs now, what is planned, and the
 * automations (schedules, monitors) that produce it. Callers build links from
 * here rather than from literals.
 */

/** Root of the Activity section. */
export const ACTIVITY_ROOT = '/activity';

/** What runs this minute, what waits for the user, what runs next. */
export const ACTIVITY_NOW_PATH = `${ACTIVITY_ROOT}/now`;

/** Planned and past runs, monitors and syncs over time. */
export const ACTIVITY_CALENDAR_PATH = `${ACTIVITY_ROOT}/calendar`;

/** Finished runs of every kind. */
export const ACTIVITY_HISTORY_PATH = `${ACTIVITY_ROOT}/history`;

/** Every schedule across agents, agentless ones included. */
export const ACTIVITY_SCHEDULES_PATH = `${ACTIVITY_ROOT}/schedules`;

/** What the assistant is watching (moved from Settings). */
export const ACTIVITY_MONITORS_PATH = `${ACTIVITY_ROOT}/monitors`;
