import DocNavigation from './DocNavigation';
import DocWindow from './DocWindow';
import Navigation from './Navigation';
import Conversation from './conversation/Conversation';
import { ActiveState } from './models/misc';
import { useState } from 'react';

export default function Query() {
  const [navState, setNavState] = useState<ActiveState>(
    window.matchMedia('(min-width: 768px)').matches ? 'ACTIVE' : 'INACTIVE',
  );
  return (
    <>
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
    </>
  );
}
