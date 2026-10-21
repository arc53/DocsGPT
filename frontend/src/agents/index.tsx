import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useParams,
} from 'react-router-dom';

import AgentAnalytics from './AgentAnalytics';
import AgentInsights from './AgentInsights';
import AgentLogs from './AgentLogs';
import AgentRouteGuard from './AgentRouteGuard';
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

/**
 * The builder for the workflow in the URL. Keyed by the agent, so moving to
 * another workflow's edit page starts a fresh builder instead of carrying
 * the last one's canvas, ids and loaded agent over.
 */
function WorkflowBuilderForAgent() {
  const { agentId } = useParams();
  return <WorkflowBuilder key={agentId} />;
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
      {/* An agent's pages open only for a role that may use them; the
          guard sends anyone else back to the list. Each page's guard has its
          own key, so the agent it read for one page never reaches another
          (its page would take that copy without reading it again). */}
      <Route
        path="manage/edit/:agentId"
        element={
          <AgentRouteGuard key="edit" action="view">
            <NewAgent mode="edit" />
          </AgentRouteGuard>
        }
      />
      <Route
        path="manage/logs/:agentId"
        element={
          <AgentRouteGuard key="logs" action="view_logs">
            <AgentLogs />
          </AgentRouteGuard>
        }
      />
      <Route
        path="manage/analytics/:agentId"
        element={
          <AgentRouteGuard key="analytics" action="view_logs">
            <AgentAnalytics />
          </AgentRouteGuard>
        }
      />
      <Route
        path="manage/insights/:agentId"
        element={
          <AgentRouteGuard key="insights" action="view_logs">
            <AgentInsights />
          </AgentRouteGuard>
        }
      />
      <Route
        path="manage/schedules/:agentId"
        element={
          <AgentRouteGuard key="schedules" action="manage_schedules">
            <SchedulesView />
          </AgentRouteGuard>
        }
      />
      <Route path="manage/workflow/new" element={<WorkflowBuilder />} />
      <Route
        path="manage/workflow/edit/:agentId"
        element={
          <AgentRouteGuard key="workflow" action="view">
            <WorkflowBuilderForAgent />
          </AgentRouteGuard>
        }
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
