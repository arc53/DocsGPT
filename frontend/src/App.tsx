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

  const resizer = document.getElementById('dragMe');
  if (resizer) {
    const leftSide = resizer.previousElementSibling;
    const rightSide = resizer.nextElementSibling;
    let x = 0;
    let y = 0;
    let leftWidth = 0;
    const mouseDownHandler = function (e) {
      // Get the current mouse position
      x = e.clientX;
      y = e.clientY;
      if (leftSide) {
        leftWidth = leftSide.getBoundingClientRect().width;
      }
      // Attach the listeners to `document`
      document.addEventListener('mousemove', mouseMoveHandler);
      document.addEventListener('mouseup', mouseUpHandler);
    };
    resizer.addEventListener('mousedown', mouseDownHandler);

    const mouseMoveHandler = function (e) {
      // How far the mouse has been moved
      const dx = e.clientX - x;
      const dy = e.clientY - y;
      if (resizer && resizer.parentElement) {
        const newLeftWidth =
          ((leftWidth + dx) * 100) /
          resizer.parentElement.getBoundingClientRect().width;
        if (leftSide) {
          leftSide.style.width = `${newLeftWidth}%`;
        }
      }
    };

    const mouseUpHandler = function () {
      resizer.style.removeProperty('cursor');
      document.body.style.removeProperty('cursor');
      if (leftSide) {
        leftSide.style.removeProperty('user-select');
        leftSide.style.removeProperty('pointer-events');
      }

      if (rightSide) {
        rightSide.style.removeProperty('user-select');
        rightSide.style.removeProperty('pointer-events');
      }

      // Remove the handlers of `mousemove` and `mouseup`
      document.removeEventListener('mousemove', mouseMoveHandler);
      document.removeEventListener('mouseup', mouseUpHandler);
    };
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
              <div className="docNavigation">
                <DocNavigation />
              </div>
              <div className="resizer" id="dragMe"></div>
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
