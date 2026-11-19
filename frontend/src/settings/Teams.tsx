import { Navigate, Route, Routes } from 'react-router-dom';

import TeamDetail from '../teams/page/TeamDetail';
import TeamsList from '../teams/page/TeamsList';
import { TEAMS_ROOT } from '../teams/page/teamTabs';

/**
 * The Teams area under `/teams/*`: the list at `/teams`, one team's page at
 * `/teams/:teamId/:tab?`.
 */
export default function Teams() {
  return (
    <Routes>
      <Route index element={<TeamsList />} />
      <Route path=":teamId/:tab?" element={<TeamDetail />} />
      <Route path="*" element={<Navigate to={TEAMS_ROOT} replace />} />
    </Routes>
  );
}
