import { Navigate, Route, Routes, useLocation } from 'react-router-dom';

import AgentLogs from './AgentLogs';
import AgentsList from './AgentsList';
import NewAgent from './NewAgent';
import { AGENTS_MANAGE_ROOT } from './paths';
import SchedulesView from './schedules/SchedulesView';
import SharedAgent from './SharedAgent';
import WorkflowBuilder from './workflow/WorkflowBuilder';

/**
 * Sends a pre-split management URL to its `/agents/manage` equivalent,
 * keeping the rest of the path and any query. Bookmarks and older links
 * (including the e2e specs' direct `goto`s) keep working.
 */
function LegacyManageRedirect() {
  const location = useLocation();
  const suffix = location.pathname.replace(/^\/agents/, '');
  return (
    <Navigate to={`${AGENTS_MANAGE_ROOT}${suffix}${location.search}`} replace />
  );
}

export default function Agents() {
  return (
    <Routes>
      {/* Managing agents. */}
      <Route path="manage" element={<AgentsList />} />
      <Route path="manage/templates" element={<AgentsList />} />
      <Route path="manage/mine" element={<AgentsList />} />
      <Route path="manage/team" element={<AgentsList />} />
      <Route path="manage/discovered" element={<AgentsList />} />
      <Route path="manage/new" element={<NewAgent mode="new" />} />
      <Route path="manage/edit/:agentId" element={<NewAgent mode="edit" />} />
      <Route path="manage/logs/:agentId" element={<AgentLogs />} />
      <Route path="manage/schedules/:agentId" element={<SchedulesView />} />
      <Route path="manage/workflow/new" element={<WorkflowBuilder />} />
      <Route
        path="manage/workflow/edit/:agentId"
        element={<WorkflowBuilder />}
      />

      {/* Using an agent someone shared. */}
      <Route path="shared/:agentId" element={<SharedAgent />} />

      {/* Pre-split URLs. `/agents` keeps its `?folder=` on the way through. */}
      <Route index element={<LegacyManageRedirect />} />
      <Route path="new" element={<LegacyManageRedirect />} />
      <Route path="edit/:agentId" element={<LegacyManageRedirect />} />
      <Route path="logs/:agentId" element={<LegacyManageRedirect />} />
      <Route path="schedules/:agentId" element={<LegacyManageRedirect />} />
      <Route path="workflow/*" element={<LegacyManageRedirect />} />
      <Route path="*" element={<Navigate to={AGENTS_MANAGE_ROOT} replace />} />
    </Routes>
  );
}
