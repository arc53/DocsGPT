import { useEffect, useState } from 'react';
import Navigation from './components/Navigation/Navigation';
import DocsGPT from './components/DocsGPT';
import './App.css';

function App() {
  const [isMobile, setIsMobile] = useState(true);

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
    <div className={`${isMobile ? 'flex-col' : 'flex-row'} flex`}>
      <Navigation isMobile={isMobile} />
      <DocsGPT />
    </div>
  );
}

export default App;
