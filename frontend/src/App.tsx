import { useEffect, useState } from 'react';
import { Routes, Route } from 'react-router-dom';
import Navigation from './components/Navigation/Navigation';
import DocsGPT from './components/DocsGPT';
import APIKeyModal from './components/APIKeyModal';
import About from './components/About';

export default function App() {
  //Currently using primitive state management. Will most likely be replaced with Redux.
  const [isMobile, setIsMobile] = useState(true);
  const [isMenuOpen, setIsMenuOpen] = useState(true);
  const [isApiModalOpen, setIsApiModalOpen] = useState(false);
  const [apiKey, setApiKey] = useState('');

  const handleResize = () => {
    if (window.innerWidth > 768 && isMobile) {
      setIsMobile(false);
    } else {
      setIsMobile(true);
    }
  };

  useEffect(() => {
    window.addEventListener('resize', handleResize);
    handleResize();

    return () => {
      window.removeEventListener('resize', handleResize);
    };
  }, []);

  return (
    <div
      className={`${
        isMobile ? 'flex-col' : 'flex-row'
      } relative flex transition-all`}
    >
      <APIKeyModal
        apiKey={apiKey}
        setApiKey={setApiKey}
        isApiModalOpen={isApiModalOpen}
        setIsApiModalOpen={setIsApiModalOpen}
      />
      <Navigation
        isMobile={isMobile}
        isMenuOpen={isMenuOpen}
        setIsMenuOpen={setIsMenuOpen}
        setIsApiModalOpen={setIsApiModalOpen}
      />
      <Routes>
        <Route path="/" element={<DocsGPT isMenuOpen={isMenuOpen} />} />
        <Route path="/about" element={<About isMenuOpen={isMenuOpen} />} />
      </Routes>
    </div>
  );
}
