import { Routes, Route } from 'react-router-dom';
import Navigation from './components/Navigation';
import Conversation from './components/Conversation/Conversation';
import APIKeyModal from './components/APIKeyModal';
import About from './components/About';
import { useState } from 'react';
import { NavState } from './models/misc';

export default function App() {
  const [navState, setNavState] = useState<NavState>('OPEN');

  return (
    <div className="min-h-full min-w-full transition-all">
      <APIKeyModal />
      <Navigation
        navState={navState}
        setNavState={(val: NavState) => setNavState(val)}
      />
      <div
        className={`${
          navState === 'OPEN' ? 'ml-0 md:ml-72 lg:ml-96' : ' ml-0 md:ml-16'
        }`}
      >
        <Routes>
          <Route path="/" element={<Conversation />} />
          <Route path="/about" element={<About />} />
        </Routes>
      </div>
    </div>
  );
}
