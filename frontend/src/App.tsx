import { Routes, Route } from 'react-router-dom';
import Navigation from './Navigation';
import DocNavigation from './DocNavigation';
import DocWindow from './DocWindow';
import Conversation from './conversation/Conversation';
import { useState } from 'react';
import { ActiveState } from './models/misc';
import { inject } from '@vercel/analytics';
import Login from './Login';
import Register from './Register';

inject();

export default function App() {
  //TODO : below media query is disjoint from tailwind. Please wire it together.
  const [navState, setNavState] = useState<ActiveState>(
    window.matchMedia('(min-width: 768px)').matches ? 'ACTIVE' : 'INACTIVE',
  );

  const [initialPos, setInitialPos] = useState(null);
  const [initialSize, setInitialSize] = useState(null);

  const initial = (e) => {

    let resizable = document.getElementById('Resizable');

    setInitialPos(e.clientX);
    setInitialSize(resizable.offsetWidth);

  }

  const resize = (e) => {

    let resizable = document.getElementById('Resizable');

    resizable.style.width = `${parseInt(initialSize) + parseInt(e.clientX - initialPos)}px`;

  }

  return (
    <>
      <Routes>
        <Route path="/" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route
          path="/query"
          element={
            <div className="wrapper">
              <div className='Block'>
                <div id='Resizable'>
                  <div className="docNavigation">
                    <DocNavigation />
                  </div>
                </div>
                <div id='Draggable'
                  draggable='true'
                  onDragStart={initial}
                  onDrag={resize}
                />
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
