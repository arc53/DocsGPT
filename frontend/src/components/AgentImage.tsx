import { useState, useEffect } from 'react';
import Robot from '../assets/robot.svg';

type AgentImageProps = {
  src?: string | null;
  alt?: string;
  className?: string;
  fallbackSrc?: string;
};

export default function AgentImage({
  src,
  alt = 'agent',
  className = '',
  fallbackSrc = Robot,
}: AgentImageProps) {
  const [currentSrc, setCurrentSrc] = useState(
    src && src.trim() !== '' ? src : fallbackSrc,
  );

  useEffect(() => {
    const newSrc = src && src.trim() !== '' ? src : fallbackSrc;
    if (newSrc !== currentSrc) {
      setCurrentSrc(newSrc);
    }
  }, [src, fallbackSrc]);

  return (
    <img
      src={currentSrc}
      alt={alt}
      className={className}
      referrerPolicy="no-referrer"
      crossOrigin="anonymous"
      onError={() => {
        if (currentSrc !== fallbackSrc) setCurrentSrc(fallbackSrc);
      }}
    />
  );
}
