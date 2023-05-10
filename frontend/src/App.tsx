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

  const [startX, setStartX] = useState(0); // [startX, setStartX
  const totalWidth = window.innerWidth;

  const [widths, setWidths] = useState([15, 35, 35, 15]);

  const handleDragStart = (event: any, ui: { x: number }) => {
    setStartX(ui.x);
  };

  const handleDrag = (index: number, event: any, ui: any) => {
    const preWidthforCurrent = widths[index];
    const preWidthforNextOne = widths[index + 1];
    const currentWidth = (event.clientX / totalWidth) * 100;
    const diff = ((ui.x - startX) / totalWidth) * 100;
    console.log('diff: ' + diff);

    const newWidths = [...widths];
    newWidths[index] = preWidthforCurrent + diff;
    newWidths[index + 1] = preWidthforNextOne - diff;
    setWidths(newWidths);

    // console.log(newWidths);
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
                  onStart={(e: any, ui: { x: any }) => handleDragStart(e, ui)}
                  onDrag={(e: any, ui: { x: any }) => handleDrag(index, e, ui)}
                  key={index}
                >
                  <div
                    className="column"
                    style={{ width: `${width}%`, float: 'left' }}
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
