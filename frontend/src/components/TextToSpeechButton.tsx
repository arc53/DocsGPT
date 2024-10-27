import { useState } from 'react';
import Speaker from '../assets/speaker.svg?react';
import Stopspeech from '../assets/stopspeech.svg?react';
import EasySpeech from 'easy-speech';

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

  const handleSpeakClick = async (text: string) => {
    if (isSpeaking) {
      EasySpeech.cancel();
      setIsSpeaking(false);
      return;
    } // Stop ongoing speech if already speaking

    try {
      await EasySpeech.init(); // Initialize EasySpeech
      setIsSpeaking(true);
      
      EasySpeech.speak({
        text,
        onend: () => setIsSpeaking(false),  // Reset when speech ends
        onerror: () => {
          console.error('Speech synthesis failed.');
          setIsSpeaking(false);
        },
      });
    } catch (error) {
      console.error('Failed to initialize speech synthesis', error);
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
