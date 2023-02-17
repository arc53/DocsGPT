import { Routes, Route } from 'react-router-dom';
import Navigation from './Navigation';
import Conversation from './conversation/Conversation';
import APIKeyModal from './preferences/APIKeyModal';
import About from './About';
import { useState } from 'react';
import { ActiveState } from './models/misc';
import { selectApiKeyStatus } from './preferences/preferenceSlice';
import { useSelector } from 'react-redux';

export default function App() {
  const isApiKeySet = useSelector(selectApiKeyStatus);
  const [navState, setNavState] = useState<ActiveState>('ACTIVE');
  const [apiKeyModalState, setApiKeyModalState] = useState<ActiveState>(
    isApiKeySet ? 'INACTIVE' : 'ACTIVE',
  );

  return (
    <div className="min-h-full min-w-full transition-all">
      <APIKeyModal
        modalState={apiKeyModalState}
        setModalState={setApiKeyModalState}
        isCancellable={isApiKeySet}
      />
      <Navigation
        navState={navState}
        setNavState={(val: ActiveState) => setNavState(val)}
        setApiKeyModalState={setApiKeyModalState}
      />
      <div
        className={`${
          navState === 'ACTIVE' ? 'ml-0 md:ml-72 lg:ml-96' : ' ml-0 md:ml-16'
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
