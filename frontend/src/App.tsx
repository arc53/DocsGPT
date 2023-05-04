import { Routes, Route } from 'react-router-dom';
import Navigation from './Navigation';
import DocNavigation from './DocNavigation';
import DocWindow from './DocWindow';
import Conversation from './conversation/Conversation';
import { useState } from 'react';
import { ActiveState } from './models/misc';
import { inject } from '@vercel/analytics';
import Login from './Login';

inject();

export default function App() {
  //TODO : below media query is disjoint from tailwind. Please wire it together.
  const [navState, setNavState] = useState<ActiveState>(
    window.matchMedia('(min-width: 768px)').matches ? 'ACTIVE' : 'INACTIVE',
  );

  return (
    <>
      <Routes>
        <Route path="/" element={<Login />} />
        <Route
          path="/query"
          element={
            <div className="wrapper">
              <div className="docNavigation">
                <DocNavigation />
              </div>
              <div className="docWindow">
                <DocWindow />
              </div>
              <div className="chatWindow">
                <Conversation />
              </div>
              <div className="chatNavigation">
                {' '}
                <Navigation navState={navState} setNavState={setNavState} />
              </div>
            </div>
          }
        />
      </Routes>
    </>
  );
}
