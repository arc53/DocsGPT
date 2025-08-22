import { Route, Routes } from 'react-router-dom';

import AgentLogs from './AgentLogs';
import AgentsList from './AgentsList';
import NewAgent from './NewAgent';
import SharedAgent from './SharedAgent';

export default function Agents() {
  return (
    <Routes>
      <Route path="/" element={<AgentsList />} />
      <Route path="/new" element={<NewAgent mode="new" />} />
      <Route path="/edit/:agentId" element={<NewAgent mode="edit" />} />
      <Route path="/logs/:agentId" element={<AgentLogs />} />
      <Route path="/shared/:agentId" element={<SharedAgent />} />
    </Routes>
  );
}
