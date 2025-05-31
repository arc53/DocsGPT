import { Navigate, useParams } from 'react-router-dom';

export default function SharedAgentGate() {
  const { agentId } = useParams();

  return <Navigate to={`/agents/shared/${agentId}`} replace />;
}
