import { useState } from 'react';
import Speaker from '../assets/speaker.svg?react';
import Stopspeech from '../assets/stopspeech.svg?react';

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

  const handleSpeakClick = (text: string) => {
    if (isSpeaking) {
      window.speechSynthesis.cancel();
      setIsSpeaking(false);
      return;
    } // Stop ongoing speech if already speaking

    const utterance = new SpeechSynthesisUtterance(text);
    setIsSpeaking(true);

    utterance.onend = () => {
      setIsSpeaking(false); // Reset when speech ends
    };

    utterance.onerror = () => {
      console.error('Speech synthesis failed.');
      setIsSpeaking(false);
    };

    window.speechSynthesis.speak(utterance);
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
          onClick={() => handleSpeakClick(text)}
          onMouseEnter={() => setIsSpeakHovered(true)}
          onMouseLeave={() => setIsSpeakHovered(false)}
        />
      ) : (
        <Speaker
          className="cursor-pointer fill-none"
          onClick={() => handleSpeakClick(text)}
          onMouseEnter={() => setIsSpeakHovered(true)}
          onMouseLeave={() => setIsSpeakHovered(false)}
        />
      )}
    </div>
  );
}
