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

// LRU Cache for audio
const audioCache = new Map<string, string>();
const MAX_CACHE_SIZE = 10;

function getCachedAudio(text: string): string | undefined {
  const cached = audioCache.get(text);
  if (cached) {
    audioCache.delete(text);
    audioCache.set(text, cached);
  }
  return cached;
}

function setCachedAudio(text: string, audioBase64: string) {
  if (audioCache.has(text)) {
    audioCache.delete(text);
  }
  if (audioCache.size >= MAX_CACHE_SIZE) {
    const firstKey = audioCache.keys().next().value;
    if (firstKey !== undefined) {
      audioCache.delete(firstKey);
    }
  }

  audioCache.set(text, audioBase64);
}

export default function SpeakButton({ text }: { text: string }) {
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      // Abort any pending fetch request
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }

      // Stop any playing audio
      if (audioRef.current) {
        audioRef.current.pause();
        if (currentlyPlayingAudio?.audio === audioRef.current) {
          currentlyPlayingAudio = null;
        }
        audioRef.current = null;
      }

      // Clear global loading request if it's this component's
      if (currentLoadingRequest) {
        currentLoadingRequest = null;
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
      const cachedAudio = getCachedAudio(text);
      let audioBase64: string;

      if (cachedAudio) {
        audioBase64 = cachedAudio;
        setIsLoading(false);
      } else {
        const abortController = new AbortController();
        abortControllerRef.current = abortController;

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
        abortControllerRef.current = null;
        currentLoadingRequest = null;

        if (data.success && data.audio_base64) {
          audioBase64 = data.audio_base64;
          // Store in cache
          setCachedAudio(text, audioBase64);
          setIsLoading(false);
        } else {
          console.error('Failed to retrieve audio.');
          setIsLoading(false);
          return;
        }
      }

      const audio = new Audio(`data:audio/mp3;base64,${audioBase64}`);
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
    } catch (error: any) {
      abortControllerRef.current = null;
      currentLoadingRequest = null;

      if (error.name === 'AbortError') {
        return;
      }
      console.error('Error fetching audio from TTS endpoint', error);
      setIsLoading(false);
    }
  };

  return (
    <button
      type="button"
      className={`flex cursor-pointer items-center justify-center rounded-full p-2 ${
        isSpeaking || isLoading
          ? 'dark:bg-purple-taupe bg-[#EEEEEE]'
          : 'bg-white-3000 dark:hover:bg-purple-taupe hover:bg-[#EEEEEE] dark:bg-transparent'
      }`}
      onClick={handleSpeakClick}
      aria-label={
        isLoading
          ? 'Loading audio'
          : isSpeaking
            ? 'Stop speaking'
            : 'Speak text'
      }
      disabled={isLoading}
    >
      {isLoading ? (
        <LoadingIcon className="animate-spin" />
      ) : isSpeaking ? (
        <Stopspeech className="fill-none" />
      ) : (
        <Speaker className="fill-none" />
      )}
    </button>
  );
}
