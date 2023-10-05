import { Routes, Route } from 'react-router-dom';
import Navigation from './Navigation';
import Conversation from './conversation/Conversation';
import About from './About';
import { inject } from '@vercel/analytics';
import { useMediaQuery } from './hooks';

inject();

export default function App() {
  const { isMobile } = useMediaQuery();
  return (
    <div className="min-h-full min-w-full">
      <Navigation />
      <div
        className={`transition-all duration-200 ${
          !isMobile ? 'ml-0 md:ml-72 lg:ml-60' : 'ml-0 md:ml-16'
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
