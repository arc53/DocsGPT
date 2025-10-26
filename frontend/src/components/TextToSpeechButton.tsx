import { useState, useRef, useEffect } from 'react';
import Speaker from '../assets/speaker.svg?react';
import Stopspeech from '../assets/stopspeech.svg?react';
import LoadingIcon from '../assets/Loading.svg?react'; // Add a loading icon SVG here

const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

let currentlyPlayingAudio: {
  audio: HTMLAudioElement;
  stopCallback: () => void;
} | null = null;

let currentLoadingRequest: {
  abortController: AbortController;
  stopLoadingCallback: () => void;
} | null = null;

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
  const [isLoading, setIsLoading] = useState(false);
  const [isSpeakHovered, setIsSpeakHovered] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        if (currentlyPlayingAudio?.audio === audioRef.current) {
          currentlyPlayingAudio = null;
        }
        audioRef.current = null;
      }
    };
  }, []);

  const handleSpeakClick = async () => {
    if (isSpeaking) {
      audioRef.current?.pause();
      audioRef.current = null;
      currentlyPlayingAudio = null;
      setIsSpeaking(false);
      return;
    }

    // Stop any currently playing audio
    if (currentlyPlayingAudio) {
      currentlyPlayingAudio.audio.pause();
      currentlyPlayingAudio.stopCallback();
      currentlyPlayingAudio = null;
    }

    // Abort any pending loading request
    if (currentLoadingRequest) {
      currentLoadingRequest.abortController.abort();
      currentLoadingRequest.stopLoadingCallback();
      currentLoadingRequest = null;
    }

    try {
      setIsLoading(true);

      const abortController = new AbortController();
      currentLoadingRequest = {
        abortController,
        stopLoadingCallback: () => {
          setIsLoading(false);
        },
      };

      const response = await fetch(apiHost + '/api/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
        signal: abortController.signal,
      });

      const data = await response.json();
      currentLoadingRequest = null;

      if (data.success && data.audio_base64) {
        const audio = new Audio(`data:audio/mp3;base64,${data.audio_base64}`);
        audioRef.current = audio;

        currentlyPlayingAudio = {
          audio,
          stopCallback: () => {
            setIsSpeaking(false);
            audioRef.current = null;
          },
        };

        audio.play().then(() => {
          setIsSpeaking(true);
          setIsLoading(false);

          audio.onended = () => {
            setIsSpeaking(false);
            audioRef.current = null;
            if (currentlyPlayingAudio?.audio === audio) {
              currentlyPlayingAudio = null;
            }
          };
        });
      } else {
        console.error('Failed to retrieve audio.');
        setIsLoading(false);
      }
    } catch (error: any) {
      if (error.name === 'AbortError') {
        return;
      }
      console.error('Error fetching audio from TTS endpoint', error);
      setIsLoading(false);
      currentLoadingRequest = null;
    }
  };

  return (
    <div
      className={`flex items-center justify-center rounded-full p-2 ${
        isSpeakHovered
          ? `dark:bg-purple-taupe bg-[#EEEEEE]`
          : `bg-[${colorLight ? colorLight : '#FFFFFF'}] dark:bg-[${colorDark ? colorDark : 'transparent'}]`
      }`}
    >
      {isLoading ? (
        <LoadingIcon className="animate-spin" />
      ) : isSpeaking ? (
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
