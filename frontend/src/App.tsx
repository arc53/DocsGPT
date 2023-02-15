import { Routes, Route } from 'react-router-dom';
import Navigation from './components/Navigation';
import Conversation from './components/Conversation/Conversation';
import APIKeyModal from './components/APIKeyModal';
import About from './components/About';

export default function App() {
  return (
    <div className="relative flex flex-col transition-all md:flex-row">
      <APIKeyModal />
      <Navigation />
      <Routes>
        <Route path="/" element={<Conversation />} />
        <Route path="/about" element={<About />} />
      </Routes>
    </div>
  );
}
