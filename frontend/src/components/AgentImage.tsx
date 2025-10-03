import { useState } from 'react';
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
  const initialSrc = src && src.trim() !== '' ? src : fallbackSrc;
  const [currentSrc, setCurrentSrc] = useState(initialSrc);

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


