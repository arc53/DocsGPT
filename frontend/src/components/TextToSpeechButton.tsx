import { useState, useRef } from 'react';
import Speaker from '../assets/speaker.svg?react';
import Stopspeech from '../assets/stopspeech.svg?react';
const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

export default function SpeakButton({
  text,
  colorLight,
  colorDark,
}: {
  text: string;
  colorLight?: string;
  colorDark?: string;
}) {
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isSpeakHovered, setIsSpeakHovered] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null); // Reference to the audio object

  const handleSpeakClick = async () => {
    if (isSpeaking) {
      // Stop audio if currently playing and reset the state
      audioRef.current?.pause();
      audioRef.current = null;
      setIsSpeaking(false);
      return;
    }

    try {
      setIsSpeaking(true);

      // Make a POST request to the /api/tts endpoint
      const response = await fetch(apiHost + '/api/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });

      const data = await response.json();

      if (data.success && data.audio_base64) {
        const audio = new Audio(`data:audio/mp3;base64,${data.audio_base64}`);
        audioRef.current = audio; // Store the audio object in ref for later control
        audio.play();

        // Reset state when audio ends
        audio.onended = () => {
          setIsSpeaking(false);
          audioRef.current = null;
        };
      } else {
        console.error('Failed to retrieve audio.');
        setIsSpeaking(false);
      }
    } catch (error) {
      console.error('Error fetching audio from TTS endpoint', error);
      setIsSpeaking(false);
    }
  };

  return (
    <div
      className={`flex items-center justify-center rounded-full p-2 ${
        isSpeakHovered
          ? `bg-[#EEEEEE] dark:bg-purple-taupe`
          : `bg-[${colorLight ? colorLight : '#FFFFFF'}] dark:bg-[${colorDark ? colorDark : 'transparent'}]`
      }`}
    >
      {isSpeaking ? (
        <Stopspeech
          className="cursor-pointer fill-none"
          onClick={handleSpeakClick}
          onMouseEnter={() => setIsSpeakHovered(true)}
          onMouseLeave={() => setIsSpeakHovered(false)}
        />
      ) : (
        <Speaker
          className="cursor-pointer fill-none"
          onClick={handleSpeakClick}
          onMouseEnter={() => setIsSpeakHovered(true)}
          onMouseLeave={() => setIsSpeakHovered(false)}
        />
      )}
    </div>
  );
}
