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
import Draggable from 'react-draggable';

inject();

export default function App() {
  //TODO : below media query is disjoint from tailwind. Please wire it together.
  const [navState, setNavState] = useState<ActiveState>(
    window.matchMedia('(min-width: 768px)').matches ? 'ACTIVE' : 'INACTIVE',
  );

  const [widths, setWidths] = useState([15, 35, 35, 15]);

  const [startX, setStartX] = useState(0); // [startX, setStartX
  const totalWidth = window.innerWidth;

  const handleDragStart = (event: any) => {
    setStartX(event.clientX);
  };

  const handleDrag = (index: number, event: any) => {
    if (index == 3) {
      return;
    } // do nothing with the last division.

    const preWidthforCurrent = widths[index];
    const preWidthforNextOne = widths[index + 1];
    const pixelDiff = event.clientX - startX;
    const diff = (pixelDiff / totalWidth) * 100;
    console.log('diff: ' + diff);

    const newWidths = [...widths];
    newWidths[index] = preWidthforCurrent + (diff / totalWidth) * 100;
    newWidths[index + 1] = preWidthforNextOne - (diff / totalWidth) * 100;
    setWidths(newWidths);
  };

  return (
    <>
      <Routes>
        <Route path="/" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route
          path="/query"
          element={
            <div className="wrapper">
              {widths.map((width, index) => (
                <Draggable
                  axis="x"
                  bounds={{ right: window.innerWidth }}
                  position={{ x: widths[index], y: 0 }}
                  onStart={(e: any) => handleDragStart(e)}
                  onDrag={(e: any) => handleDrag(index, e)}
                  key={index}
                >
                  <div
                    className="column"
                    style={{
                      width: `${width}%`,
                    }}
                  >
                    {index === 0 && <DocNavigation />}
                    {index === 1 && <DocWindow />}
                    {index === 2 && <Conversation />}
                    {index === 3 && (
                      <Navigation
                        navState={navState}
                        setNavState={setNavState}
                      />
                    )}
                  </div>
                </Draggable>
              ))}
            </div>
          }
        />
      </Routes>
    </>
  );
}
