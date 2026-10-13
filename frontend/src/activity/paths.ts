/**
 * Routes of the Activity section: what runs now, what is planned, and the
 * automations (schedules, monitors) that produce it. Callers build links from
 * here rather than from literals.
 */

/** Root of the Activity section. */
export const ACTIVITY_ROOT = '/activity';

/** Every schedule across agents, agentless ones included. */
export const ACTIVITY_SCHEDULES_PATH = `${ACTIVITY_ROOT}/schedules`;

/** What the assistant is watching (moved from Settings). */
export const ACTIVITY_MONITORS_PATH = `${ACTIVITY_ROOT}/monitors`;
