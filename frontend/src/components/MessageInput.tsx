import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { LoaderCircle, Mic, Square } from 'lucide-react';
import { useDropzone } from 'react-dropzone';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector, useStore } from 'react-redux';

import type { RootState } from '../store';

import endpoints from '../api/endpoints';
import userService from '../api/services/userService';
import AlertIcon from '../assets/alert.svg';
import ClipIcon from '../assets/clip.svg';
import DragFileUpload from '../assets/DragFileUpload.svg';
import ExitIcon from '../assets/exit.svg';
import SendArrowIcon from './SendArrowIcon';
import SourceIcon from '../assets/source.svg';
import DocumentationDark from '../assets/documentation-dark.svg';
import ToolIcon from '../assets/tool.svg';
import {
  addAttachment,
  removeAttachment,
  selectAttachments,
  updateAttachment,
  reorderAttachments,
} from '../upload/uploadSlice';

import { ActiveState, Doc } from '../models/misc';
import {
  selectSelectedDocs,
  selectToken,
} from '../preferences/preferenceSlice';
import Upload from '../upload/Upload';
import { getOS, isTouchDevice } from '../utils/browserUtils';
import SourcesPopup from './SourcesPopup';
import ToolsPopup from './ToolsPopup';
import { handleAbort } from '../conversation/conversationSlice';
import {
  AUDIO_FILE_ACCEPT_ATTR,
  FILE_UPLOAD_ACCEPT,
  FILE_UPLOAD_ACCEPT_ATTR,
} from '../constants/fileUpload';

const generateId = (): string =>
  `${Date.now()}-${Math.random().toString(36).substring(2)}`;

type RecordingState = 'idle' | 'recording' | 'transcribing' | 'error';

const LIVE_TRANSCRIPTION_TIMESLICE_MS = 1000;
const LIVE_CAPTURE_SAMPLE_RATE = 16000;
const LIVE_CAPTURE_MAX_BUFFER_SECONDS = 20;
const LIVE_SILENCE_RMS_THRESHOLD = 0.015;
const ENABLE_VOICE_INPUT = import.meta.env.VITE_ENABLE_VOICE_INPUT === 'true';

type AudioContextWindow = Window &
  typeof globalThis & {
    webkitAudioContext?: typeof AudioContext;
  };

type LegacyNavigator = Navigator & {
  getUserMedia?: (
    constraints: MediaStreamConstraints,
    successCallback: (stream: MediaStream) => void,
    errorCallback: (error: DOMException) => void,
  ) => void;
  webkitGetUserMedia?: (
    constraints: MediaStreamConstraints,
    successCallback: (stream: MediaStream) => void,
    errorCallback: (error: DOMException) => void,
  ) => void;
  mozGetUserMedia?: (
    constraints: MediaStreamConstraints,
    successCallback: (stream: MediaStream) => void,
    errorCallback: (error: DOMException) => void,
  ) => void;
};

type LiveAudioSnapshot = {
  blob: Blob;
  chunkIndex: number;
  isSilence: boolean;
};

const getAudioContextConstructor = (): typeof AudioContext | null => {
  if (typeof window === 'undefined') {
    return null;
  }

  const audioWindow = window as AudioContextWindow;
  return audioWindow.AudioContext || audioWindow.webkitAudioContext || null;
};

const getLegacyGetUserMedia = () => {
  if (typeof navigator === 'undefined') {
    return null;
  }

  const legacyNavigator = navigator as LegacyNavigator;
  return (
    legacyNavigator.getUserMedia ||
    legacyNavigator.webkitGetUserMedia ||
    legacyNavigator.mozGetUserMedia ||
    null
  );
};

const getVoiceInputSupportError = (): string | null => {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') {
    return 'Voice input is unavailable right now.';
  }

  if (!window.isSecureContext) {
    return 'Voice input requires a secure connection (HTTPS or localhost).';
  }

  if (!navigator.mediaDevices?.getUserMedia && !getLegacyGetUserMedia()) {
    return 'Voice input is not available in this browser.';
  }

  if (!getAudioContextConstructor()) {
    return 'Voice input requires Web Audio support in this browser.';
  }

  return null;
};

const getUserMediaStream = (
  constraints: MediaStreamConstraints,
): Promise<MediaStream> => {
  if (navigator.mediaDevices?.getUserMedia) {
    return navigator.mediaDevices.getUserMedia(constraints);
  }

  const legacyGetUserMedia = getLegacyGetUserMedia();
  if (!legacyGetUserMedia) {
    return Promise.reject(
      new Error('Voice input is not available in this browser.'),
    );
  }

  return new Promise((resolve, reject) => {
    legacyGetUserMedia.call(navigator, constraints, resolve, reject);
  });
};

const getVoiceInputErrorMessage = (error: unknown): string => {
  if (typeof window !== 'undefined' && !window.isSecureContext) {
    return 'Voice input requires a secure connection (HTTPS or localhost).';
  }

  if (error instanceof DOMException) {
    switch (error.name) {
      case 'NotAllowedError':
      case 'PermissionDeniedError':
      case 'SecurityError':
        return 'Microphone access was blocked. Allow microphone permission and try again.';
      case 'NotFoundError':
      case 'DevicesNotFoundError':
        return 'No microphone was found on this device.';
      case 'NotReadableError':
      case 'TrackStartError':
        return 'The microphone is unavailable or already in use.';
      case 'AbortError':
        return 'Microphone access was interrupted before recording started.';
      default:
        break;
    }
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return 'Microphone access was denied.';
};

const downsampleFloat32Buffer = (
  source: Float32Array,
  inputSampleRate: number,
  outputSampleRate: number,
): Float32Array => {
  if (
    !source.length ||
    inputSampleRate <= 0 ||
    outputSampleRate <= 0 ||
    inputSampleRate === outputSampleRate
  ) {
    return source;
  }

  if (outputSampleRate > inputSampleRate) {
    return source;
  }

  const ratio = inputSampleRate / outputSampleRate;
  const outputLength = Math.max(1, Math.round(source.length / ratio));
  const output = new Float32Array(outputLength);

  let outputOffset = 0;
  let inputOffset = 0;
  while (outputOffset < output.length) {
    const nextInputOffset = Math.min(
      source.length,
      Math.round((outputOffset + 1) * ratio),
    );
    let accumulator = 0;
    let count = 0;
    for (let index = inputOffset; index < nextInputOffset; index += 1) {
      accumulator += source[index];
      count += 1;
    }
    output[outputOffset] =
      count > 0 ? accumulator / count : source[inputOffset];
    outputOffset += 1;
    inputOffset = nextInputOffset;
  }

  return output;
};

const concatenateFloat32Chunks = (
  chunks: Float32Array[],
  totalLength: number,
): Float32Array => {
  const output = new Float32Array(totalLength);
  let offset = 0;
  chunks.forEach((chunk) => {
    output.set(chunk, offset);
    offset += chunk.length;
  });
  return output;
};

const encodeWavFromFloat32 = (
  samples: Float32Array,
  sampleRate: number,
): Blob => {
  const bytesPerSample = 2;
  const blockAlign = bytesPerSample;
  const buffer = new ArrayBuffer(44 + samples.length * bytesPerSample);
  const view = new DataView(buffer);
  let offset = 0;

  const writeString = (value: string) => {
    for (let index = 0; index < value.length; index += 1) {
      view.setUint8(offset + index, value.charCodeAt(index));
    }
    offset += value.length;
  };

  writeString('RIFF');
  view.setUint32(offset, 36 + samples.length * bytesPerSample, true);
  offset += 4;
  writeString('WAVE');
  writeString('fmt ');
  view.setUint32(offset, 16, true);
  offset += 4;
  view.setUint16(offset, 1, true);
  offset += 2;
  view.setUint16(offset, 1, true);
  offset += 2;
  view.setUint32(offset, sampleRate, true);
  offset += 4;
  view.setUint32(offset, sampleRate * blockAlign, true);
  offset += 4;
  view.setUint16(offset, blockAlign, true);
  offset += 2;
  view.setUint16(offset, 16, true);
  offset += 2;
  writeString('data');
  view.setUint32(offset, samples.length * bytesPerSample, true);
  offset += 4;

  for (let index = 0; index < samples.length; index += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(
      offset,
      clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff,
      true,
    );
    offset += 2;
  }

  return new Blob([buffer], { type: 'audio/wav' });
};

type MessageInputProps = {
  onSubmit: (text: string) => void;
  loading: boolean;
  showSourceButton?: boolean;
  showToolButton?: boolean;
  autoFocus?: boolean;
};

export default function MessageInput({
  onSubmit,
  loading,
  showSourceButton = true,
  showToolButton = true,
  autoFocus = true,
}: MessageInputProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState('');
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const voiceFileInputRef = useRef<HTMLInputElement>(null);
  const sourceButtonRef = useRef<HTMLButtonElement>(null);
  const toolButtonRef = useRef<HTMLButtonElement>(null);
  const [isSourcesPopupOpen, setIsSourcesPopupOpen] = useState(false);
  const [isToolsPopupOpen, setIsToolsPopupOpen] = useState(false);
  const [uploadModalState, setUploadModalState] =
    useState<ActiveState>('INACTIVE');
  const [handleDragActive, setHandleDragActive] = useState<boolean>(false);
  const [recordingState, setRecordingState] = useState<RecordingState>('idle');
  const [voiceError, setVoiceError] = useState<string | null>(null);

  const selectedDocs = useSelector(selectSelectedDocs);
  const token = useSelector(selectToken);
  const attachments = useSelector(selectAttachments);

  const dispatch = useDispatch();
  const store = useStore<RootState>();
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioSourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const audioProcessorNodeRef = useRef<ScriptProcessorNode | null>(null);
  const audioSilenceGainRef = useRef<GainNode | null>(null);
  const snapshotIntervalRef = useRef<number | null>(null);
  const pcmChunksRef = useRef<Float32Array[]>([]);
  const totalBufferedSamplesRef = useRef(0);
  const totalCapturedSamplesRef = useRef(0);
  const lastSnapshotCapturedSamplesRef = useRef(0);
  const recentWindowRmsRef = useRef({ sumSquares: 0, sampleCount: 0 });
  const liveSessionIdRef = useRef<string | null>(null);
  const livePendingSnapshotRef = useRef<LiveAudioSnapshot | null>(null);
  const liveChunkIndexRef = useRef(0);
  const liveUploadInFlightRef = useRef(false);
  const liveStopRequestedRef = useRef(false);
  const voiceBaseValueRef = useRef('');
  const liveTranscriptRef = useRef('');

  const browserOS = getOS();
  const isTouch = isTouchDevice();

  const stopMediaStream = () => {
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
  };

  const stopAudioProcessing = () => {
    if (snapshotIntervalRef.current !== null) {
      window.clearInterval(snapshotIntervalRef.current);
      snapshotIntervalRef.current = null;
    }

    if (audioProcessorNodeRef.current) {
      audioProcessorNodeRef.current.onaudioprocess = null;
      audioProcessorNodeRef.current.disconnect();
      audioProcessorNodeRef.current = null;
    }
    if (audioSourceNodeRef.current) {
      audioSourceNodeRef.current.disconnect();
      audioSourceNodeRef.current = null;
    }
    if (audioSilenceGainRef.current) {
      audioSilenceGainRef.current.disconnect();
      audioSilenceGainRef.current = null;
    }
    if (audioContextRef.current) {
      void audioContextRef.current.close().catch(() => undefined);
      audioContextRef.current = null;
    }
    stopMediaStream();
  };

  const resetLiveTranscriptionState = () => {
    pcmChunksRef.current = [];
    totalBufferedSamplesRef.current = 0;
    totalCapturedSamplesRef.current = 0;
    lastSnapshotCapturedSamplesRef.current = 0;
    recentWindowRmsRef.current = { sumSquares: 0, sampleCount: 0 };
    liveSessionIdRef.current = null;
    livePendingSnapshotRef.current = null;
    liveChunkIndexRef.current = 0;
    liveUploadInFlightRef.current = false;
    liveStopRequestedRef.current = false;
    voiceBaseValueRef.current = '';
    liveTranscriptRef.current = '';
  };

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        ((browserOS === 'win' || browserOS === 'linux') &&
          event.ctrlKey &&
          event.key === 'k') ||
        (browserOS === 'mac' && event.metaKey && event.key === 'k')
      ) {
        event.preventDefault();
        setIsSourcesPopupOpen((s) => !s);
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [browserOS]);

  useEffect(() => {
    return () => {
      stopAudioProcessing();
      resetLiveTranscriptionState();
    };
  }, []);

  const uploadFiles = useCallback(
    (files: File[]) => {
      if (!files || files.length === 0) return;

      const apiHost = import.meta.env.VITE_API_HOST;

      if (files.length > 1) {
        const formData = new FormData();
        const indexToUiId: Record<number, string> = {};

        files.forEach((file, i) => {
          formData.append('file', file);
          const uiId = generateId();
          indexToUiId[i] = uiId;
          dispatch(
            addAttachment({
              id: uiId,
              fileName: file.name,
              progress: 0,
              status: 'uploading' as const,
              taskId: '',
            }),
          );
        });

        const xhr = new XMLHttpRequest();

        xhr.upload.addEventListener('progress', (event) => {
          if (event.lengthComputable) {
            const progress = Math.round((event.loaded / event.total) * 100);
            Object.values(indexToUiId).forEach((uiId) =>
              dispatch(
                updateAttachment({
                  id: uiId,
                  updates: { progress },
                }),
              ),
            );
          }
        });

        xhr.onload = () => {
          const status = xhr.status;
          if (status === 200) {
            try {
              const response = JSON.parse(xhr.responseText);

              if (Array.isArray(response?.tasks)) {
                const tasks = response.tasks as Array<{
                  task_id?: string;
                  filename?: string;
                  attachment_id?: string;
                  path?: string;
                  upload_index?: number;
                }>;
                const errors = Array.isArray(response?.errors)
                  ? (response.errors as Array<{
                      filename?: string;
                      error?: string;
                      upload_index?: number;
                    }>)
                  : [];
                const hasIndexedResults =
                  tasks.some((task) => typeof task.upload_index === 'number') ||
                  errors.some(
                    (errorItem) => typeof errorItem.upload_index === 'number',
                  );

                if (hasIndexedResults) {
                  const tasksByIndex = new Map<
                    number,
                    (typeof tasks)[number]
                  >();
                  const failedIndices = new Set<number>();

                  tasks.forEach((task, taskOrderIndex) => {
                    const uploadIndex =
                      typeof task.upload_index === 'number'
                        ? task.upload_index
                        : taskOrderIndex;
                    tasksByIndex.set(uploadIndex, task);
                  });

                  errors.forEach((errorItem) => {
                    if (typeof errorItem.upload_index === 'number') {
                      failedIndices.add(errorItem.upload_index);
                    }
                  });

                  files.forEach((_, index) => {
                    const uiId = indexToUiId[index];
                    if (!uiId) return;

                    const task = tasksByIndex.get(index);
                    if (task?.task_id) {
                      dispatch(
                        updateAttachment({
                          id: uiId,
                          updates: {
                            taskId: task.task_id,
                            // Stash the server's attachment id so SSE
                            // ``attachment.*`` events (Phase 3A) can
                            // match this row by ``scope.id`` and drive
                            // the per-attachment push-fresh poll gate.
                            attachmentId: task.attachment_id,
                            status: 'processing',
                            progress: 10,
                          },
                        }),
                      );
                      return;
                    }

                    if (failedIndices.has(index)) {
                      dispatch(
                        updateAttachment({
                          id: uiId,
                          updates: { status: 'failed' },
                        }),
                      );
                      return;
                    }

                    dispatch(
                      updateAttachment({
                        id: uiId,
                        updates: { status: 'failed' },
                      }),
                    );
                  });
                } else {
                  tasks.forEach((t, idx) => {
                    const uiId = indexToUiId[idx];
                    if (!uiId) return;
                    if (t?.task_id) {
                      dispatch(
                        updateAttachment({
                          id: uiId,
                          updates: {
                            taskId: t.task_id,
                            attachmentId: t.attachment_id,
                            status: 'processing',
                            progress: 10,
                          },
                        }),
                      );
                    } else {
                      dispatch(
                        updateAttachment({
                          id: uiId,
                          updates: { status: 'failed' },
                        }),
                      );
                    }
                  });

                  if (tasks.length < files.length) {
                    for (let i = tasks.length; i < files.length; i++) {
                      const uiId = indexToUiId[i];
                      if (uiId) {
                        dispatch(
                          updateAttachment({
                            id: uiId,
                            updates: { status: 'failed' },
                          }),
                        );
                      }
                    }
                  }
                }
              } else if (response?.task_id) {
                if (files.length === 1) {
                  const uiId = indexToUiId[0];
                  if (uiId) {
                    dispatch(
                      updateAttachment({
                        id: uiId,
                        updates: {
                          taskId: response.task_id,
                          attachmentId: response.attachment_id,
                          status: 'processing',
                          progress: 10,
                        },
                      }),
                    );
                  }
                } else {
                  console.warn(
                    'Server returned a single task_id for multiple files. Update backend to return tasks[].',
                  );
                  const firstUi = indexToUiId[0];
                  if (firstUi) {
                    dispatch(
                      updateAttachment({
                        id: firstUi,
                        updates: {
                          taskId: response.task_id,
                          status: 'processing',
                          progress: 10,
                        },
                      }),
                    );
                  }
                  for (let i = 1; i < files.length; i++) {
                    const uiId = indexToUiId[i];
                    if (uiId) {
                      dispatch(
                        updateAttachment({
                          id: uiId,
                          updates: { status: 'failed' },
                        }),
                      );
                    }
                  }
                }
              } else {
                console.error('Unexpected upload response shape', response);
                Object.values(indexToUiId).forEach((id) =>
                  dispatch(
                    updateAttachment({
                      id,
                      updates: { status: 'failed' },
                    }),
                  ),
                );
              }
            } catch (err) {
              console.error(
                'Failed to parse upload response',
                err,
                xhr.responseText,
              );
              Object.values(indexToUiId).forEach((id) =>
                dispatch(
                  updateAttachment({
                    id,
                    updates: { status: 'failed' },
                  }),
                ),
              );
            }
          } else {
            console.error('Upload failed', status, xhr.responseText);
            Object.values(indexToUiId).forEach((id) =>
              dispatch(
                updateAttachment({
                  id,
                  updates: { status: 'failed' },
                }),
              ),
            );
          }
        };

        xhr.onerror = () => {
          console.error('Upload network error');
          Object.values(indexToUiId).forEach((id) =>
            dispatch(
              updateAttachment({
                id,
                updates: { status: 'failed' },
              }),
            ),
          );
        };

        xhr.open('POST', `${apiHost}${endpoints.USER.STORE_ATTACHMENT}`);
        if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
        xhr.send(formData);
        return;
      }

      // Single-file path: upload each file individually (original repo behavior)
      files.forEach((file) => {
        const formData = new FormData();
        formData.append('file', file);
        const xhr = new XMLHttpRequest();
        const uniqueId = generateId();

        const newAttachment = {
          id: uniqueId,
          fileName: file.name,
          progress: 0,
          status: 'uploading' as const,
          taskId: '',
        };

        dispatch(addAttachment(newAttachment));

        xhr.upload.addEventListener('progress', (event) => {
          if (event.lengthComputable) {
            const progress = Math.round((event.loaded / event.total) * 100);
            dispatch(
              updateAttachment({
                id: uniqueId,
                updates: { progress },
              }),
            );
          }
        });

        xhr.onload = () => {
          if (xhr.status === 200) {
            try {
              const response = JSON.parse(xhr.responseText);
              if (response.task_id) {
                dispatch(
                  updateAttachment({
                    id: uniqueId,
                    updates: {
                      taskId: response.task_id,
                      attachmentId: response.attachment_id,
                      status: 'processing',
                      progress: 10,
                    },
                  }),
                );
              } else {
                // If backend returned tasks[] for single-file, handle gracefully:
                if (
                  Array.isArray(response?.tasks) &&
                  response.tasks[0]?.task_id
                ) {
                  dispatch(
                    updateAttachment({
                      id: uniqueId,
                      updates: {
                        taskId: response.tasks[0].task_id,
                        attachmentId: response.tasks[0].attachment_id,
                        status: 'processing',
                        progress: 10,
                      },
                    }),
                  );
                } else {
                  dispatch(
                    updateAttachment({
                      id: uniqueId,
                      updates: { status: 'failed' },
                    }),
                  );
                }
              }
            } catch (err) {
              console.error(
                'Failed to parse upload response',
                err,
                xhr.responseText,
              );
              dispatch(
                updateAttachment({
                  id: uniqueId,
                  updates: { status: 'failed' },
                }),
              );
            }
          } else {
            dispatch(
              updateAttachment({
                id: uniqueId,
                updates: { status: 'failed' },
              }),
            );
          }
        };

        xhr.onerror = () => {
          dispatch(
            updateAttachment({
              id: uniqueId,
              updates: { status: 'failed' },
            }),
          );
        };

        xhr.open('POST', `${apiHost}${endpoints.USER.STORE_ATTACHMENT}`);
        if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
        xhr.send(formData);
      });
    },
    [dispatch, token],
  );

  const handleFileAttachment = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
    const files = Array.from(e.target.files);
    uploadFiles(files);
    // clear input so same file can be selected again
    e.target.value = '';
  };

  // Drag & drop via react-dropzone
  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      uploadFiles(acceptedFiles);
      setHandleDragActive(false);
    },
    [uploadFiles],
  );

  const { getRootProps, getInputProps } = useDropzone({
    onDrop,
    noClick: true,
    noKeyboard: true,
    multiple: true,
    onDragEnter: () => {
      setHandleDragActive(true);
    },
    onDragLeave: () => {
      setHandleDragActive(false);
    },
    maxSize: 25000000,
    accept: FILE_UPLOAD_ACCEPT,
  });

  useEffect(() => {
    /**
     * Phase 4C: skip the per-attachment poll round-trip when SSE is
     * driving this attachment's lifecycle. The slice's
     * ``attachment.*`` ``extraReducer`` flips ``status``/``progress``
     * directly on incoming events, so a network poll would only
     * confirm what's already on screen. Mirrors the per-task gate
     * pattern from Upload.tsx / FileTree.tsx.
     */
    const PUSH_FRESH_WINDOW_MS = 30_000;
    const isAttachmentPushFresh = (attachment: {
      attachmentId?: string;
      lastEventAt?: number;
    }): boolean => {
      const state = store.getState();
      if (state.notifications.health !== 'healthy') return false;
      if (!attachment.attachmentId) return false;
      if (!attachment.lastEventAt) return false;
      return Date.now() - attachment.lastEventAt < PUSH_FRESH_WINDOW_MS;
    };

    const checkTaskStatus = () => {
      const processingAttachments = attachments.filter(
        (att) => att.status === 'processing' && att.taskId,
      );

      processingAttachments.forEach((attachment) => {
        if (isAttachmentPushFresh(attachment)) return;
        userService
          .getTaskStatus(attachment.taskId!, null)
          .then((data) => data.json())
          .then((data) => {
            if (data.status === 'SUCCESS') {
              dispatch(
                updateAttachment({
                  id: attachment.id,
                  updates: {
                    status: 'completed',
                    progress: 100,
                    id: data.result?.attachment_id,
                    token_count: data.result?.token_count,
                  },
                }),
              );
            } else if (data.status === 'FAILURE') {
              dispatch(
                updateAttachment({
                  id: attachment.id,
                  updates: { status: 'failed' },
                }),
              );
            } else if (data.status === 'PROGRESS' && data.result?.current) {
              dispatch(
                updateAttachment({
                  id: attachment.id,
                  updates: { progress: data.result.current },
                }),
              );
            }
          })
          .catch(() => {
            dispatch(
              updateAttachment({
                id: attachment.id,
                updates: { status: 'failed' },
              }),
            );
          });
      });
    };

    const interval = setInterval(() => {
      if (attachments.some((att) => att.status === 'processing')) {
        checkTaskStatus();
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [attachments, dispatch, store]);

  const handleInput = useCallback(() => {
    if (inputRef.current) {
      if (window.innerWidth < 350) inputRef.current.style.height = 'auto';
      else inputRef.current.style.height = '64px';
      inputRef.current.style.height = `${Math.min(
        inputRef.current.scrollHeight,
        96,
      )}px`;
    }
  }, []);

  const buildVoiceDraftValue = (baseText: string, transcript: string) => {
    const normalizedBaseText = baseText ?? '';
    const normalizedTranscript = transcript.trim();

    if (!normalizedTranscript) {
      return normalizedBaseText;
    }

    return normalizedBaseText.trim()
      ? `${normalizedBaseText}${
          normalizedBaseText.endsWith('\n') ? '' : '\n'
        }${normalizedTranscript}`
      : normalizedTranscript;
  };

  const applyLiveTranscript = (transcript: string) => {
    const normalizedTranscript = transcript.trim();
    liveTranscriptRef.current = normalizedTranscript;
    setValue(
      buildVoiceDraftValue(voiceBaseValueRef.current, normalizedTranscript),
    );
    setTimeout(() => {
      handleInput();
    }, 0);
  };

  const promptVoiceFileFallback = (message: string) => {
    setRecordingState('idle');
    setVoiceError(`${message} Choose or record an audio file instead.`);
    setTimeout(() => {
      voiceFileInputRef.current?.click();
    }, 0);
  };

  const transcribeUploadedAudioFile = async (file: File) => {
    try {
      setVoiceError(null);
      setRecordingState('transcribing');
      voiceBaseValueRef.current = value;
      liveTranscriptRef.current = '';

      const response = await userService.transcribeAudio(file, token);
      const data = await response.json();

      if (!response.ok || !data?.success) {
        throw new Error(data?.message || 'Failed to transcribe audio.');
      }

      if (typeof data.text !== 'string' || !data.text.trim()) {
        throw new Error('No transcript was returned for this audio file.');
      }

      applyLiveTranscript(data.text);
      setRecordingState('idle');
      if (autoFocus) {
        setTimeout(() => {
          inputRef.current?.focus();
        }, 0);
      }
    } catch (error) {
      console.error('Uploaded audio transcription failed', error);
      setRecordingState('error');
      setVoiceError(
        error instanceof Error ? error.message : 'Failed to transcribe audio.',
      );
    }
  };

  const trimLivePcmBuffer = () => {
    const maxBufferedSamples =
      LIVE_CAPTURE_SAMPLE_RATE * LIVE_CAPTURE_MAX_BUFFER_SECONDS;

    while (
      totalBufferedSamplesRef.current > maxBufferedSamples &&
      pcmChunksRef.current.length > 1
    ) {
      const removedChunk = pcmChunksRef.current.shift();
      if (!removedChunk) {
        break;
      }
      totalBufferedSamplesRef.current -= removedChunk.length;
    }

    if (
      totalBufferedSamplesRef.current > maxBufferedSamples &&
      pcmChunksRef.current.length === 1
    ) {
      const onlyChunk = pcmChunksRef.current[0];
      if (!onlyChunk || onlyChunk.length <= maxBufferedSamples) {
        return;
      }

      const trimmedChunk = onlyChunk.slice(
        onlyChunk.length - maxBufferedSamples,
      );
      pcmChunksRef.current = [trimmedChunk];
      totalBufferedSamplesRef.current = trimmedChunk.length;
    }
  };

  const cleanupLiveSession = async () => {
    const sessionId = liveSessionIdRef.current;
    if (!sessionId) {
      return;
    }

    liveSessionIdRef.current = null;
    try {
      await userService.finishLiveTranscription(sessionId, token);
    } catch {
      // Best-effort cleanup only.
    }
  };

  const failLiveTranscription = async (message: string) => {
    console.error('Live audio transcription failed', message);
    stopAudioProcessing();
    await cleanupLiveSession();
    resetLiveTranscriptionState();
    setRecordingState('error');
    setVoiceError(message);
  };

  const finalizeLiveTranscription = async () => {
    const sessionId = liveSessionIdRef.current;
    if (!sessionId) {
      resetLiveTranscriptionState();
      setRecordingState('idle');
      return;
    }

    try {
      const response = await userService.finishLiveTranscription(
        sessionId,
        token,
      );
      const data = await response.json();

      if (!response.ok || !data?.success) {
        throw new Error(
          data?.message || 'Failed to finalize live transcription.',
        );
      }

      if (typeof data.text === 'string') {
        applyLiveTranscript(data.text);
      }

      setRecordingState('idle');
      if (autoFocus) {
        setTimeout(() => {
          inputRef.current?.focus();
        }, 0);
      }
    } catch (error) {
      console.error('Finalizing live audio transcription failed', error);
      setRecordingState('error');
      setVoiceError(
        error instanceof Error
          ? error.message
          : 'Failed to finalize live transcription.',
      );
    } finally {
      resetLiveTranscriptionState();
    }
  };

  const maybeFinalizeLiveTranscription = async () => {
    if (
      !liveStopRequestedRef.current ||
      liveUploadInFlightRef.current ||
      livePendingSnapshotRef.current
    ) {
      return;
    }

    await finalizeLiveTranscription();
  };

  const processPendingLiveSnapshot = async () => {
    if (liveUploadInFlightRef.current) {
      return;
    }

    const nextSnapshot = livePendingSnapshotRef.current;
    const sessionId = liveSessionIdRef.current;
    if (!nextSnapshot || !sessionId) {
      await maybeFinalizeLiveTranscription();
      return;
    }

    livePendingSnapshotRef.current = null;
    liveUploadInFlightRef.current = true;

    try {
      const file = new File(
        [nextSnapshot.blob],
        `voice-live-${nextSnapshot.chunkIndex}.wav`,
        {
          type: 'audio/wav',
        },
      );
      const response = await userService.transcribeLiveAudioChunk(
        sessionId,
        nextSnapshot.chunkIndex,
        file,
        token,
        nextSnapshot.isSilence,
      );
      const data = await response.json();

      if (!response.ok || !data?.success) {
        throw new Error(data?.message || 'Failed to transcribe audio.');
      }

      if (typeof data.transcript_text === 'string') {
        applyLiveTranscript(data.transcript_text);
      }
    } catch (error) {
      await failLiveTranscription(
        error instanceof Error ? error.message : 'Failed to transcribe audio.',
      );
      return;
    } finally {
      liveUploadInFlightRef.current = false;
    }

    if (livePendingSnapshotRef.current) {
      void processPendingLiveSnapshot();
      return;
    }

    void maybeFinalizeLiveTranscription();
  };

  const queueCurrentLiveSnapshot = (forceSilence = false) => {
    if (
      totalCapturedSamplesRef.current === lastSnapshotCapturedSamplesRef.current
    ) {
      return;
    }

    if (!pcmChunksRef.current.length || totalBufferedSamplesRef.current <= 0) {
      return;
    }

    const pcmSnapshot = concatenateFloat32Chunks(
      pcmChunksRef.current,
      totalBufferedSamplesRef.current,
    );
    if (!pcmSnapshot.length) {
      return;
    }

    const { sumSquares, sampleCount } = recentWindowRmsRef.current;
    const averageRms =
      sampleCount > 0 ? Math.sqrt(sumSquares / sampleCount) : 0;
    const isSilence = forceSilence || averageRms < LIVE_SILENCE_RMS_THRESHOLD;

    recentWindowRmsRef.current = { sumSquares: 0, sampleCount: 0 };
    lastSnapshotCapturedSamplesRef.current = totalCapturedSamplesRef.current;
    livePendingSnapshotRef.current = {
      blob: encodeWavFromFloat32(pcmSnapshot, LIVE_CAPTURE_SAMPLE_RATE),
      chunkIndex: liveChunkIndexRef.current,
      isSilence,
    };
    liveChunkIndexRef.current += 1;
    void processPendingLiveSnapshot();
  };

  const handleVoiceInput = async () => {
    if (recordingState === 'transcribing') {
      return;
    }

    if (recordingState === 'recording') {
      setRecordingState('transcribing');
      liveStopRequestedRef.current = true;
      stopAudioProcessing();
      queueCurrentLiveSnapshot();
      void maybeFinalizeLiveTranscription();
      return;
    }

    const voiceInputSupportError = getVoiceInputSupportError();
    if (voiceInputSupportError) {
      promptVoiceFileFallback(voiceInputSupportError);
      return;
    }

    const AudioContextConstructor = getAudioContextConstructor();
    if (!AudioContextConstructor) {
      setRecordingState('error');
      setVoiceError('Voice input requires Web Audio support in this browser.');
      return;
    }

    let stream: MediaStream | null = null;
    try {
      setVoiceError(null);
      stream = await getUserMediaStream({ audio: true });
    } catch (error) {
      promptVoiceFileFallback(getVoiceInputErrorMessage(error));
      return;
    }

    try {
      const liveStartResponse = await userService.startLiveTranscription(token);
      const liveStartData = await liveStartResponse.json();
      if (!liveStartResponse.ok || !liveStartData?.success) {
        throw new Error(
          liveStartData?.message || 'Failed to start live transcription.',
        );
      }

      const audioContext = new AudioContextConstructor();
      await audioContext.resume().catch(() => undefined);
      const sourceNode = audioContext.createMediaStreamSource(stream);
      const processorNode = audioContext.createScriptProcessor(4096, 1, 1);
      const silenceGain = audioContext.createGain();
      silenceGain.gain.value = 0;

      pcmChunksRef.current = [];
      totalBufferedSamplesRef.current = 0;
      totalCapturedSamplesRef.current = 0;
      lastSnapshotCapturedSamplesRef.current = 0;
      recentWindowRmsRef.current = { sumSquares: 0, sampleCount: 0 };
      liveSessionIdRef.current = liveStartData.session_id;
      livePendingSnapshotRef.current = null;
      liveChunkIndexRef.current = 0;
      liveUploadInFlightRef.current = false;
      liveStopRequestedRef.current = false;
      voiceBaseValueRef.current = value;
      liveTranscriptRef.current = '';
      applyLiveTranscript('');

      processorNode.onaudioprocess = (event: AudioProcessingEvent) => {
        const inputData = event.inputBuffer.getChannelData(0);
        if (!inputData.length) {
          return;
        }

        const capturedChunk = new Float32Array(inputData.length);
        capturedChunk.set(inputData);

        const downsampledChunk = downsampleFloat32Buffer(
          capturedChunk,
          audioContext.sampleRate,
          LIVE_CAPTURE_SAMPLE_RATE,
        );
        if (!downsampledChunk.length) {
          return;
        }

        pcmChunksRef.current.push(downsampledChunk);
        totalBufferedSamplesRef.current += downsampledChunk.length;
        totalCapturedSamplesRef.current += downsampledChunk.length;

        let sumSquares = 0;
        for (let index = 0; index < downsampledChunk.length; index += 1) {
          const sample = downsampledChunk[index];
          sumSquares += sample * sample;
        }

        recentWindowRmsRef.current.sumSquares += sumSquares;
        recentWindowRmsRef.current.sampleCount += downsampledChunk.length;
        trimLivePcmBuffer();
      };

      sourceNode.connect(processorNode);
      processorNode.connect(silenceGain);
      silenceGain.connect(audioContext.destination);

      mediaStreamRef.current = stream;
      audioContextRef.current = audioContext;
      audioSourceNodeRef.current = sourceNode;
      audioProcessorNodeRef.current = processorNode;
      audioSilenceGainRef.current = silenceGain;
      snapshotIntervalRef.current = window.setInterval(() => {
        if (!liveStopRequestedRef.current) {
          queueCurrentLiveSnapshot();
        }
      }, LIVE_TRANSCRIPTION_TIMESLICE_MS);

      setRecordingState('recording');
    } catch (error) {
      console.error('Live voice transcription failed', error);
      stream?.getTracks().forEach((track) => track.stop());
      stopAudioProcessing();
      await cleanupLiveSession();
      resetLiveTranscriptionState();
      setRecordingState('error');
      setVoiceError(
        error instanceof Error
          ? error.message
          : 'Failed to start live transcription.',
      );
    }
  };

  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    handleInput();
  }, [handleInput]);

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    handleInput();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
      handleInput();
    }
  };

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const clipboardItems = e.clipboardData?.items;
    const files: File[] = [];

    if (!clipboardItems) return;

    for (let i = 0; i < clipboardItems.length; i++) {
      const item = clipboardItems[i];

      if (item.kind === 'file') {
        const file = item.getAsFile();
        if (file) {
          files.push(file);
        }
      }
    }

    if (files.length > 0) {
      // Prevent weird binary stuff from being pasted as text
      e.preventDefault();
      uploadFiles(files);
    }
  };

  const handleVoiceFileAttachment = (
    e: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const file = e.target.files?.[0];
    e.target.value = '';

    if (!file) {
      return;
    }

    void transcribeUploadedAudioFile(file);
  };

  const handlePostDocumentSelect = (_docs: Doc[] | null) => {
    // SourcesPopup updates Redux selection directly; this preserves the prop contract.
    void _docs;
  };

  const handleSubmit = () => {
    if (
      value.trim() &&
      !loading &&
      recordingState !== 'recording' &&
      recordingState !== 'transcribing'
    ) {
      onSubmit(value);
      setValue('');
      if (isTouch) {
        inputRef.current?.blur();
      } else if (autoFocus) {
        setTimeout(() => {
          if (isMountedRef.current) {
            inputRef.current?.focus();
          }
        }, 0);
      }
    }
  };

  const handleCancel = () => {
    handleAbort();
  };

  const [draggingId, setDraggingId] = useState<string | null>(null);

  const findIndexById = (id: string) =>
    attachments.findIndex((a) => a.id === id);

  const handleDragStart = (e: React.DragEvent, id: string) => {
    setDraggingId(id);
    try {
      e.dataTransfer.setData('text/plain', id);
      e.dataTransfer.effectAllowed = 'move';
    } catch {
      // ignore
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  };

  const handleDropOn = (e: React.DragEvent, targetId: string) => {
    e.preventDefault();
    const sourceId = e.dataTransfer.getData('text/plain');
    if (!sourceId || sourceId === targetId) return;

    const sourceIndex = findIndexById(sourceId);
    const destIndex = findIndexById(targetId);
    if (sourceIndex === -1 || destIndex === -1) return;

    dispatch(reorderAttachments({ sourceIndex, destinationIndex: destIndex }));
    setDraggingId(null);
  };

  const voiceButtonLabel =
    recordingState === 'recording'
      ? 'Stop recording'
      : recordingState === 'transcribing'
        ? 'Transcribing audio'
        : 'Voice input';
  const voiceButtonText =
    recordingState === 'recording'
      ? 'Stop'
      : recordingState === 'transcribing'
        ? 'Transcribing'
        : 'Voice';

  return (
    <div {...getRootProps()} className="flex w-full flex-col">
      {/* react-dropzone input (for drag/drop) */}
      <input {...getInputProps()} />
      <input
        ref={voiceFileInputRef}
        type="file"
        className="hidden"
        accept={AUDIO_FILE_ACCEPT_ATTR}
        capture="user"
        onChange={handleVoiceFileAttachment}
      />

      <div className="border-border bg-card relative flex w-full flex-col rounded-[23px] border dark:bg-transparent">
        <div className="flex flex-wrap gap-1.5 px-2 py-2 sm:gap-2 sm:px-3">
          {attachments.map((attachment) => {
            return (
              <div
                key={attachment.id}
                draggable={true}
                onDragStart={(e) => handleDragStart(e, attachment.id)}
                onDragOver={handleDragOver}
                onDrop={(e) => handleDropOn(e, attachment.id)}
                className={`group dark:text-foreground bg-muted text-muted-foreground dark:bg-accent relative flex items-center rounded-xl px-2 py-1 text-[12px] sm:px-3 sm:py-1.5 sm:text-[14px] ${
                  attachment.status !== 'completed'
                    ? 'opacity-70'
                    : 'opacity-100'
                } ${
                  draggingId === attachment.id
                    ? 'ring-dashed opacity-60 ring-2 ring-purple-200'
                    : ''
                }`}
                title={attachment.fileName}
              >
                <div className="bg-primary mr-2 flex h-8 w-8 items-center justify-center rounded-md p-1">
                  {attachment.status === 'completed' && (
                    <img
                      src={DocumentationDark}
                      alt="Attachment"
                      className="h-[15px] w-[15px] object-fill"
                    />
                  )}

                  {attachment.status === 'failed' && (
                    <img
                      src={AlertIcon}
                      alt="Failed"
                      className="h-[15px] w-[15px] object-fill"
                    />
                  )}

                  {(attachment.status === 'uploading' ||
                    attachment.status === 'processing') && (
                    <div className="flex h-[15px] w-[15px] items-center justify-center">
                      <svg className="h-[15px] w-[15px]" viewBox="0 0 24 24">
                        <circle
                          className="opacity-0"
                          cx="12"
                          cy="12"
                          r="10"
                          stroke="transparent"
                          strokeWidth="4"
                          fill="none"
                        />
                        <circle
                          className="text-[#ECECF1]"
                          cx="12"
                          cy="12"
                          r="10"
                          stroke="currentColor"
                          strokeWidth="4"
                          fill="none"
                          strokeDasharray="62.83"
                          strokeDashoffset={
                            62.83 * (1 - attachment.progress / 100)
                          }
                          transform="rotate(-90 12 12)"
                        />
                      </svg>
                    </div>
                  )}
                </div>

                <span className="max-w-[120px] truncate font-medium sm:max-w-[150px]">
                  {attachment.fileName}
                </span>

                <button
                  className="ml-1.5 flex items-center justify-center rounded-full p-1"
                  onClick={() => {
                    dispatch(removeAttachment(attachment.id));
                  }}
                  aria-label={t('conversation.attachments.remove')}
                >
                  <img
                    src={ExitIcon}
                    alt={t('conversation.attachments.remove')}
                    className="h-2.5 w-2.5 filter dark:invert"
                  />
                </button>
              </div>
            );
          })}
        </div>

        {voiceError && (
          <div className="px-2 pb-1 text-xs text-[#B42318] sm:px-3">
            {voiceError}
          </div>
        )}

        <div className="w-full">
          <label htmlFor="message-input" className="sr-only">
            {t('inputPlaceholder')}
          </label>
          <textarea
            id="message-input"
            ref={inputRef}
            value={value}
            autoFocus={autoFocus && !isTouch}
            onChange={handleChange}
            readOnly={
              recordingState === 'recording' ||
              recordingState === 'transcribing'
            }
            tabIndex={1}
            placeholder={t('inputPlaceholder')}
            className="inputbox-style no-scrollbar dark:text-foreground dark:placeholder:text-muted-foreground/50 w-full overflow-x-hidden overflow-y-auto rounded-t-[23px] bg-transparent px-2 text-base leading-tight whitespace-pre-wrap opacity-100 placeholder:text-gray-500 focus:outline-hidden sm:px-3"
            onInput={handleInput}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            aria-label={t('inputPlaceholder')}
          />
        </div>

        <div className="flex items-center px-2 pb-1.5 sm:px-3 sm:pb-2">
          <div className="flex grow flex-wrap gap-1 sm:gap-2">
            {showSourceButton && (
              <button
                ref={sourceButtonRef}
                className="xs:px-3 xs:py-1.5 dark:border-border border-border hover:bg-accent dark:hover:bg-muted flex max-w-[130px] items-center rounded-[32px] border px-2 py-1 transition-colors sm:max-w-[150px]"
                onClick={() => setIsSourcesPopupOpen(!isSourcesPopupOpen)}
                title={
                  selectedDocs && selectedDocs.length > 0
                    ? selectedDocs.map((doc) => doc.name).join(', ')
                    : t('conversation.sources.title')
                }
              >
                <img
                  src={SourceIcon}
                  alt="Sources"
                  className="mr-1 h-3.5 w-3.5 shrink-0 sm:mr-1.5 sm:h-4"
                />
                <span className="xs:text-[12px] dark:text-foreground text-muted-foreground truncate overflow-hidden text-[10px] font-medium sm:text-[14px]">
                  {selectedDocs && selectedDocs.length > 0
                    ? selectedDocs.length === 1
                      ? selectedDocs[0].name
                      : `${selectedDocs.length} sources selected`
                    : t('conversation.sources.title')}
                </span>
                {!isTouch && (
                  <span className="ml-1 hidden text-[10px] text-gray-500 sm:inline-block dark:text-gray-400">
                    {browserOS === 'mac' ? '(⌘K)' : '(ctrl+K)'}
                  </span>
                )}
              </button>
            )}

            {showToolButton && (
              <button
                ref={toolButtonRef}
                className="xs:px-3 xs:py-1.5 xs:max-w-[150px] dark:border-border border-border hover:bg-muted dark:hover:bg-muted flex max-w-[130px] items-center rounded-[32px] border px-2 py-1 transition-colors"
                onClick={() => setIsToolsPopupOpen(!isToolsPopupOpen)}
              >
                <img
                  src={ToolIcon}
                  alt="Tools"
                  className="mr-1 h-3.5 w-3.5 shrink-0 sm:mr-1.5 sm:h-4 sm:w-4"
                />
                <span className="xs:text-[12px] dark:text-foreground text-muted-foreground truncate overflow-hidden text-[10px] font-medium sm:text-[14px]">
                  {t('settings.tools.label')}
                </span>
              </button>
            )}
            {ENABLE_VOICE_INPUT && (
              <button
                type="button"
                onClick={() => {
                  void handleVoiceInput();
                }}
                aria-label={voiceButtonLabel}
                title={voiceButtonLabel}
                disabled={loading || recordingState === 'transcribing'}
                className={`xs:px-3 xs:py-1.5 dark:border-border flex items-center rounded-[32px] border px-2 py-1 transition-colors ${
                  recordingState === 'recording'
                    ? 'border-[#B42318] bg-[#FEE4E2] text-[#B42318] dark:bg-[#4A2323]'
                    : 'border-border dark:hover:bg-accent hover:bg-gray-100'
                } ${
                  loading || recordingState === 'transcribing'
                    ? 'cursor-not-allowed opacity-60'
                    : ''
                }`}
              >
                {recordingState === 'transcribing' ? (
                  <LoaderCircle className="mr-1 h-3.5 w-3.5 animate-spin sm:mr-1.5 sm:h-4 sm:w-4" />
                ) : recordingState === 'recording' ? (
                  <Square className="mr-1 h-3.5 w-3.5 fill-current sm:mr-1.5 sm:h-4 sm:w-4" />
                ) : (
                  <Mic className="mr-1 h-3.5 w-3.5 sm:mr-1.5 sm:h-4 sm:w-4" />
                )}
                <span
                  className={`xs:text-[12px] dark:text-foreground text-[10px] font-medium sm:text-[14px] ${
                    recordingState === 'recording'
                      ? 'text-[#B42318]'
                      : 'text-muted-foreground'
                  }`}
                >
                  {voiceButtonText}
                </span>
              </button>
            )}
            <label className="xs:px-3 xs:py-1.5 dark:border-border border-border hover:bg-muted dark:hover:bg-muted flex cursor-pointer items-center rounded-[32px] border px-2 py-1 transition-colors">
              <img
                src={ClipIcon}
                alt="Attach"
                className="mr-1 h-3.5 w-3.5 sm:mr-1.5 sm:h-4 sm:w-4"
              />
              <span className="xs:text-[12px] dark:text-foreground text-muted-foreground text-[10px] font-medium sm:text-[14px]">
                {t('conversation.attachments.attach')}
              </span>
              <input
                type="file"
                className="hidden"
                multiple
                accept={FILE_UPLOAD_ACCEPT_ATTR}
                onChange={handleFileAttachment}
              />
            </label>
            {/* Additional badges can be added here in the future */}
          </div>

          {loading ? (
            <button
              onClick={handleCancel}
              aria-label={t('cancel')}
              className={`bg-primary ml-auto flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-white sm:h-9 sm:w-9`}
              disabled={!loading}
            >
              <div className="flex h-3 w-3 items-center justify-center rounded-[3px] bg-white sm:h-3.5 sm:w-3.5" />
            </button>
          ) : (
            <button
              onClick={handleSubmit}
              aria-label={t('send')}
              className={`ml-auto flex h-7 w-7 shrink-0 items-center justify-center rounded-full transition-colors duration-300 ease-in-out sm:h-9 sm:w-9 ${
                value.trim() &&
                !loading &&
                recordingState !== 'recording' &&
                recordingState !== 'transcribing'
                  ? 'bg-primary text-white'
                  : 'bg-muted text-muted-foreground dark:bg-accent dark:text-muted-foreground'
              }`}
              disabled={
                !value.trim() ||
                loading ||
                recordingState === 'recording' ||
                recordingState === 'transcribing'
              }
            >
              <SendArrowIcon
                className="mx-auto my-auto block h-3.5 w-3.5 sm:h-4 sm:w-4"
                aria-label={t('send')}
                role="img"
              />
            </button>
          )}
        </div>
      </div>

      <SourcesPopup
        isOpen={isSourcesPopupOpen}
        onClose={() => setIsSourcesPopupOpen(false)}
        anchorRef={sourceButtonRef}
        handlePostDocumentSelect={handlePostDocumentSelect}
        setUploadModalState={setUploadModalState}
      />

      <ToolsPopup
        isOpen={isToolsPopupOpen}
        onClose={() => setIsToolsPopupOpen(false)}
        anchorRef={toolButtonRef}
      />

      {uploadModalState === 'ACTIVE' && (
        <Upload
          receivedFile={[]}
          setModalState={setUploadModalState}
          isOnboarding={false}
          renderTab={null}
          close={() => setUploadModalState('INACTIVE')}
        />
      )}

      {handleDragActive &&
        createPortal(
          <div className="dark:bg-background/85 pointer-events-none fixed top-0 left-0 z-50 flex size-full flex-col items-center justify-center bg-white/85">
            <img className="filter dark:invert" src={DragFileUpload} />
            <span className="text-muted-foreground dark:text-muted-foreground px-2 text-2xl font-bold">
              {t('modals.uploadDoc.drag.title')}
            </span>
            <span className="text-s text-muted-foreground dark:text-muted-foreground w-48 p-2 text-center">
              {t('modals.uploadDoc.drag.description')}
            </span>
          </div>,
          document.body,
        )}
    </div>
  );
}
