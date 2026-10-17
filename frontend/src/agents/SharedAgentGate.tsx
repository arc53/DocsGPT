import { Navigate, useParams } from 'react-router-dom';

import { sharedAgentPath } from './paths';

export default function SharedAgentGate() {
  const { agentId } = useParams();

  return <Navigate to={sharedAgentPath(agentId ?? '')} replace />;
}
