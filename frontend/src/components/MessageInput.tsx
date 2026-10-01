import { envVar } from '@/env';
import { cn } from '@/lib/utils';
import { CloudUpload, Database } from 'lucide-react';
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import { useDropzone } from 'react-dropzone';
import i18n from 'i18next';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector, useStore } from 'react-redux';

import endpoints from '../api/endpoints';
import userService from '../api/services/userService';
import SendArrow from '../assets/send.svg?react';
import {
  addAttachment,
  attachmentFailureReason,
  removeAttachment,
  selectAttachments,
  toSendableAttachments,
  updateAttachment,
  reorderAttachments,
} from '../upload/uploadSlice';
import { useAddToKnowledge } from '../upload/useAddToKnowledge';

import { ActiveState, Doc } from '../models/misc';
import {
  selectAttachmentBudgetShare,
  selectSelectedDocs,
  selectSelectedModel,
  selectSourceDocs,
  selectSttAvailable,
  selectToken,
  setSelectedDocs,
} from '../preferences/preferenceSlice';
import type { AppDispatch, RootState } from '../store';
import Upload from '../upload/Upload';
import { isTouchDevice } from '../utils/browserUtils';
import { Button } from './ui/button';
import { IconButton } from './ui/icon-button';
import { type MultiSelectPopoverItem } from './MultiSelectPopover';
import ToolIcon from './ToolIcon';
import ConnectorIcon from '../connectors/ConnectorIcon';
import {
  connectionNeedsSignIn,
  loadConnectors,
  selectConnections,
  selectConnectorCatalog,
} from '../connectors/connectorsSlice';
import { toolServiceOf } from '../connectors/toolService';
import SignInAgainNotice, {
  useSignInAgain,
} from '../connectors/SignInAgainNotice';
import {
  AttachFileButton,
  AttachmentChipList,
  KnowledgeHint,
  MicButton,
  type RecordingState,
  SourcesTrigger,
  ToolsTrigger,
} from './message-input';
import { useArmedSend } from './message-input/armedSend';
import {
  ATTACHMENT_IDLE_MS,
  ATTACHMENT_MAX_BYTES,
  ATTACHMENT_QUEUE_CHECK_MS,
  ATTACHMENT_QUEUE_MAX_CHECKS,
  ATTACHMENT_UPLOAD_CONCURRENCY,
  checkAttachmentTask,
  createTaskQueue,
  uploadAttachmentFile,
} from './message-input/attachmentUpload';
import { cannotReadAttachment } from './message-input/attachmentReadability';
import { exceedsAttachmentBudget } from './message-input/attachmentBudget';
import { handleAbort } from '../conversation/conversationSlice';
import {
  AUDIO_FILE_ACCEPT_ATTR,
  getFileExtension,
  partitionAttachmentFiles,
} from '../constants/fileUpload';
import { UserToolType } from '../settings/types';
import { sourceItemId, toSourcePickerItems } from '../utils/sourceUtils';
import { showActionToast } from '../notifications/actionToastSlice';
import { isOwner } from '../utils/accessUtils';
import { isChatPickerToolVisible, toolInChat } from '../utils/toolUtils';

const generateId = (): string =>
  `${Date.now()}-${Math.random().toString(36).substring(2)}`;

const LIVE_TRANSCRIPTION_TIMESLICE_MS = 1000;
const LIVE_CAPTURE_SAMPLE_RATE = 16000;
const LIVE_CAPTURE_MAX_BUFFER_SECONDS = 20;
const LIVE_SILENCE_RMS_THRESHOLD = 0.015;
const ENABLE_VOICE_INPUT = envVar('VITE_ENABLE_VOICE_INPUT') === 'true';

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
    return i18n.t('conversation.voice.unavailable');
  }

  if (!window.isSecureContext) {
    return i18n.t('conversation.voice.insecure');
  }

  if (!navigator.mediaDevices?.getUserMedia && !getLegacyGetUserMedia()) {
    return i18n.t('conversation.voice.unsupported');
  }

  if (!getAudioContextConstructor()) {
    return i18n.t('conversation.voice.noWebAudio');
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
    return Promise.reject(new Error(i18n.t('conversation.voice.unsupported')));
  }

  return new Promise((resolve, reject) => {
    legacyGetUserMedia.call(navigator, constraints, resolve, reject);
  });
};

const getVoiceInputErrorMessage = (error: unknown): string => {
  if (typeof window !== 'undefined' && !window.isSecureContext) {
    return i18n.t('conversation.voice.insecure');
  }

  if (error instanceof DOMException) {
    switch (error.name) {
      case 'NotAllowedError':
      case 'PermissionDeniedError':
      case 'SecurityError':
        return i18n.t('conversation.voice.micBlocked');
      case 'NotFoundError':
      case 'DevicesNotFoundError':
        return i18n.t('conversation.voice.micNotFound');
      case 'NotReadableError':
      case 'TrackStartError':
        return i18n.t('conversation.voice.micBusy');
      case 'AbortError':
        return i18n.t('conversation.voice.micInterrupted');
      default:
        break;
    }
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return i18n.t('conversation.voice.micDenied');
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
  // Opt-in: enable send with empty text when there are completed
  // attachments (used by doc-driven workflow runs). Normal chat leaves this
  // unset, preserving the text-required behavior.
  allowSendWithoutText?: boolean;
  // A question queued by a send path outside the composer (hero
  // suggestion cards) while attachments were still pending: seeds the
  // input and arms the send so the standard waiting banner takes over.
  queuedQuestion?: string | null;
  onQueuedQuestionConsumed?: () => void;
};

export default function MessageInput({
  onSubmit,
  loading,
  showSourceButton = true,
  showToolButton = true,
  autoFocus = true,
  allowSendWithoutText = false,
  queuedQuestion = null,
  onQueuedQuestionConsumed,
}: MessageInputProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState('');
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const voiceFileInputRef = useRef<HTMLInputElement>(null);
  const [isSourcesPopupOpen, setIsSourcesPopupOpen] = useState(false);
  const [isToolsPopupOpen, setIsToolsPopupOpen] = useState(false);
  const [userTools, setUserTools] = useState<UserToolType[]>([]);
  const connections = useSelector(selectConnections);
  const catalog = useSelector(selectConnectorCatalog);
  const [toolsLoading, setToolsLoading] = useState(false);
  const [uploadModalState, setUploadModalState] =
    useState<ActiveState>('INACTIVE');
  const [handleDragActive, setHandleDragActive] = useState<boolean>(false);
  const [recordingState, setRecordingState] = useState<RecordingState>('idle');
  const [voiceError, setVoiceError] = useState<string | null>(null);

  const selectedDocs = useSelector(selectSelectedDocs);
  const sourceDocs = useSelector(selectSourceDocs);
  const token = useSelector(selectToken);
  const attachments = useSelector(selectAttachments);
  const selectedModel = useSelector(selectSelectedModel);
  const sttAvailable = useSelector(selectSttAvailable);
  const unreadableAttachmentIds = useMemo(
    () =>
      new Set(
        attachments
          .filter((attachment) =>
            cannotReadAttachment(
              attachment,
              selectedModel?.supported_attachment_types,
            ),
          )
          .map((attachment) => attachment.id),
      ),
    [attachments, selectedModel],
  );
  const attachmentBudgetShare = useSelector(selectAttachmentBudgetShare);
  // No cap on how many files attach: past the model's attachment budget the
  // files still send, and Knowledge is offered as the better home for them.
  const overAttachmentBudget = useMemo(
    () =>
      exceedsAttachmentBudget(
        attachments,
        selectedModel?.context_window,
        attachmentBudgetShare ?? undefined,
      ),
    [attachments, selectedModel, attachmentBudgetShare],
  );
  const knowledge = useAddToKnowledge();

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
    return () => {
      stopAudioProcessing();
      resetLiveTranscriptionState();
    };
  }, []);

  // Recover the race where attachment.* SSE arrives before the upload
  // XHR's onload sets ``attachmentId``: walk recentEvents and watchdog
  // the row so it can't stay stuck on 'processing'. Mirrors
  // Upload.tsx's ``trackTraining``.
  const trackAttachment = useCallback(
    (clientId: string, attachmentId: string, taskId: string) => {
      let handled = false;

      const check = () => {
        const state = store.getState();
        const row = state.upload.attachments.find((a) => a.id === clientId);
        if (!row) return true; // removed by user; stop tracking
        if (row.status === 'completed' || row.status === 'failed') {
          handled = true;
          return true;
        }
        for (const event of state.notifications.recentEvents) {
          if (event.scope?.id !== attachmentId) continue;
          if (event.type === 'attachment.completed') {
            const payload = (event.payload || {}) as Record<string, unknown>;
            const tokenCount = Number(payload.token_count);
            handled = true;
            dispatch(
              updateAttachment({
                id: clientId,
                updates: {
                  status: 'completed',
                  progress: 100,
                  ...(Number.isFinite(tokenCount)
                    ? { token_count: tokenCount }
                    : {}),
                  ...(typeof payload.mime_type === 'string'
                    ? { mimeType: payload.mime_type }
                    : {}),
                  ...(typeof payload.extraction_status === 'string'
                    ? { extractionStatus: payload.extraction_status }
                    : {}),
                },
              }),
            );
            return true;
          }
          if (event.type === 'attachment.failed') {
            handled = true;
            const reason = attachmentFailureReason(
              (event.payload || {}) as Record<string, unknown>,
            );
            dispatch(
              updateAttachment({
                id: clientId,
                updates: {
                  status: 'failed',
                  ...(reason ? { errorMessage: reason } : {}),
                },
              }),
            );
            return true;
          }
        }
        return false;
      };

      if (check()) return;
      // Two clocks. Until the worker takes the file (its first queued or
      // progress event) nothing is timed: a set of forty files queues behind
      // itself, and a busy worker can take many minutes to reach the last
      // one. Every ten quiet minutes the task status is asked instead; a
      // file still queued waits on, up to an hour. Once the worker has it,
      // an idle window, not a total cap: a big zip (one task per member) or a
      // slow scan keeps reporting progress, and each report restarts it.
      const activityOf = () =>
        store.getState().upload.attachments.find((a) => a.id === clientId)
          ?.activity ?? 0;
      let lastActivity = activityOf();
      let started = lastActivity > 0;
      let queueChecks = 0;
      let timer: number | undefined;
      let unsubscribe: (() => void) | null = null;
      const arm = (ms: number, onElapsed: () => void) => {
        window.clearTimeout(timer);
        timer = window.setTimeout(onElapsed, ms);
      };
      const fail = (reason: string, errorMessage?: string) => {
        window.clearTimeout(timer);
        unsubscribe?.();
        if (handled) return;
        handled = true;
        console.warn(`trackAttachment: ${reason}`, clientId, attachmentId);
        dispatch(
          updateAttachment({
            id: clientId,
            updates: {
              status: 'failed',
              ...(errorMessage ? { errorMessage } : {}),
            },
          }),
        );
      };
      const onIdle = () => fail('no progress from the worker');
      const onQueueCheck = async () => {
        if (handled || started) return;
        const task = taskId
          ? await checkAttachmentTask(taskId, token)
          : ({ state: 'unknown' } as const);
        if (handled || started) return;
        if (task.state === 'failed') {
          fail('the parse task failed', task.message);
        } else if (task.state === 'unavailable') {
          fail('no worker is running');
        } else if (task.state === 'started') {
          started = true;
          arm(ATTACHMENT_IDLE_MS, onIdle);
        } else if (++queueChecks >= ATTACHMENT_QUEUE_MAX_CHECKS) {
          fail('no worker took the file');
        } else {
          arm(ATTACHMENT_QUEUE_CHECK_MS, () => void onQueueCheck());
        }
      };
      if (started) arm(ATTACHMENT_IDLE_MS, onIdle);
      else arm(ATTACHMENT_QUEUE_CHECK_MS, () => void onQueueCheck());
      unsubscribe = store.subscribe(() => {
        if (check()) {
          window.clearTimeout(timer);
          unsubscribe?.();
          return;
        }
        const activity = activityOf();
        if (activity !== lastActivity) {
          lastActivity = activity;
          started = true;
          arm(ATTACHMENT_IDLE_MS, onIdle);
        }
      });
    },
    [dispatch, store, token],
  );

  const uploadQueueRef = useRef<ReturnType<typeof createTaskQueue> | null>(
    null,
  );
  const getUploadQueue = useCallback(() => {
    uploadQueueRef.current ??= createTaskQueue(ATTACHMENT_UPLOAD_CONCURRENCY);
    return uploadQueueRef.current;
  }, []);
  // Uploads not finished yet, by chip id: stops one (drops it from the
  // queue, aborts its request) when its chip goes.
  const uploadStoppersRef = useRef(new Map<string, () => void>());
  useEffect(() => {
    const present = new Set(attachments.map((attachment) => attachment.id));
    for (const [id, stop] of uploadStoppersRef.current) {
      if (present.has(id)) continue;
      uploadStoppersRef.current.delete(id);
      stop();
    }
  }, [attachments]);

  const uploadFiles = useCallback(
    async (incomingFiles: File[]) => {
      if (!incomingFiles || incomingFiles.length === 0) return;

      // The size limit applies the same way to picked, dropped and pasted
      // files, and a refused file shows as a failed chip that says why.
      const withinLimit = incomingFiles.filter((file) => {
        if (file.size <= ATTACHMENT_MAX_BYTES) return true;
        dispatch(
          addAttachment({
            id: generateId(),
            fileName: file.name,
            progress: 0,
            status: 'failed' as const,
            taskId: '',
            errorMessage: t('conversation.attachments.tooLarge', {
              size: Math.round(ATTACHMENT_MAX_BYTES / (1024 * 1024)),
            }),
          }),
        );
        return false;
      });
      if (withinLimit.length === 0) return;

      // Run the server's own rule here, not just the input's `accept`:
      // mobile pickers ignore `accept`, and a file the server will refuse
      // should say so before it costs an upload. Surface the refusal as a
      // failed chip so the user sees why instead of a silent drop.
      const { supported, unsupported } =
        await partitionAttachmentFiles(withinLimit);
      unsupported.forEach((file) => {
        dispatch(
          addAttachment({
            id: generateId(),
            fileName: file.name,
            progress: 0,
            status: 'failed' as const,
            taskId: '',
            errorMessage: t('conversation.attachments.unsupportedType', {
              extension: getFileExtension(file.name) || '?',
            }),
          }),
        );
      });
      if (supported.length === 0) return;
      const files = supported;

      const url = `${envVar('VITE_API_HOST')}${endpoints.USER.STORE_ATTACHMENT}`;
      const uploadFailedMessage = t('conversation.attachments.uploadFailed');

      // One request per file, a few at a time: each file gets its own
      // progress, its own error and its own response, so a slow or refused
      // file never holds back or fails the rest of the set.
      files.forEach((file) => {
        const uiId = generateId();
        dispatch(
          addAttachment({
            id: uiId,
            fileName: file.name,
            progress: 0,
            status: 'uploading' as const,
            taskId: '',
          }),
        );

        const controller = new AbortController();
        const cancel = getUploadQueue().push(async () => {
          // Removed from the composer while it waited for a slot.
          if (!store.getState().upload.attachments.some((a) => a.id === uiId))
            return;
          const outcome = await uploadAttachmentFile(file, {
            url,
            token,
            signal: controller.signal,
            onProgress: (progress) =>
              dispatch(updateAttachment({ id: uiId, updates: { progress } })),
          });
          uploadStoppersRef.current.delete(uiId);
          // Removed while it uploaded: its request was aborted, nothing to show.
          if (controller.signal.aborted) return;
          if (outcome.kind === 'stored') {
            dispatch(
              updateAttachment({
                id: uiId,
                updates: {
                  taskId: outcome.taskId,
                  // ``attachment.*`` events match the row by this id.
                  attachmentId: outcome.attachmentId,
                  status: 'processing',
                  progress: 10,
                },
              }),
            );
            if (outcome.attachmentId) {
              trackAttachment(uiId, outcome.attachmentId, outcome.taskId);
            }
            return;
          }
          dispatch(
            updateAttachment({
              id: uiId,
              updates: {
                status: 'failed',
                errorMessage:
                  outcome.kind === 'network'
                    ? uploadFailedMessage
                    : outcome.message,
              },
            }),
          );
        });
        uploadStoppersRef.current.set(uiId, () => {
          cancel();
          controller.abort();
        });
      });
    },
    [dispatch, getUploadQueue, store, t, token, trackAttachment],
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
    // The textarea below owns paste-to-attach via handlePaste. react-dropzone
    // added its own paste handling in v19.2 (on by default), which fires on the
    // root for pastes into any focused descendant - so both would upload the
    // same file. Leave paste to handlePaste.
    noPaste: true,
    multiple: true,
    onDragEnter: () => {
      setHandleDragActive(true);
    },
    onDragLeave: () => {
      setHandleDragActive(false);
    },
    // No `accept` and no `maxSize`: react-dropzone would drop a rejected
    // file on the floor with no feedback, and its mime matching disagrees
    // with the server for text files that have no parser (.py, .log).
    // uploadFiles applies the type and size rules to every path (picker,
    // drop, paste) and reports what it refuses.
  });

  const handleInput = useCallback(() => {
    if (!inputRef.current) return;
    if (window.innerWidth < 350) inputRef.current.style.height = 'auto';
    else inputRef.current.style.height = '64px';
    inputRef.current.style.height = `${Math.min(
      inputRef.current.scrollHeight,
      Math.round(window.innerHeight * 0.4),
    )}px`;
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
        throw new Error(
          data?.message || t('conversation.voice.transcribeFailed'),
        );
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
        error instanceof Error
          ? error.message
          : t('conversation.voice.transcribeFailed'),
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
          data?.message || t('conversation.voice.finalizeFailed'),
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
          : t('conversation.voice.finalizeFailed'),
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
        throw new Error(
          data?.message || t('conversation.voice.transcribeFailed'),
        );
      }

      if (typeof data.transcript_text === 'string') {
        applyLiveTranscript(data.transcript_text);
      }
    } catch (error) {
      await failLiveTranscription(
        error instanceof Error
          ? error.message
          : t('conversation.voice.transcribeFailed'),
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
      setVoiceError(t('conversation.voice.noWebAudio'));
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
          liveStartData?.message || t('conversation.voice.startFailed'),
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
          : t('conversation.voice.startFailed'),
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

  useLayoutEffect(() => {
    handleInput();
  }, [value, handleInput]);

  useEffect(() => {
    window.addEventListener('resize', handleInput);
    return () => window.removeEventListener('resize', handleInput);
  }, [handleInput]);

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
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
    // Hook point for downstream side-effects after a source is toggled.
    void _docs;
  };

  const sourceItems: MultiSelectPopoverItem[] = useMemo(
    () =>
      toSourcePickerItems(
        sourceDocs,
        {
          own: t('conversation.sources.groupOwn'),
          team: t('conversation.sources.groupTeam'),
        },
        <Database />,
      ),
    [sourceDocs, t],
  );

  const selectedSourceIds = (
    selectedDocs && Array.isArray(selectedDocs) ? selectedDocs : []
  ).map((doc) => sourceItemId(doc));

  const handleToggleSource = (id: string) => {
    if (!sourceDocs) return;
    const current = Array.isArray(selectedDocs) ? selectedDocs : [];
    const matched = current.find((doc) => sourceItemId(doc) === id);
    let updated: Doc[];
    if (matched) {
      updated = current.filter((doc) => sourceItemId(doc) !== id);
    } else {
      const incoming = sourceDocs.find((doc) => sourceItemId(doc) === id);
      if (!incoming) return;
      updated = [...current, incoming];
    }
    dispatch(setSelectedDocs(updated.length > 0 ? updated : []));
    handlePostDocumentSelect(updated.length > 0 ? updated : null);
  };

  const fetchUserTools = useCallback(() => {
    setToolsLoading(true);
    userService
      .getUserTools(token)
      .then((res) => res.json())
      .then((data) => {
        const filtered = (data.tools || []).filter(isChatPickerToolVisible);
        setUserTools(filtered);
      })
      .catch((error) => {
        console.error('Error fetching tools:', error);
      })
      .finally(() => setToolsLoading(false));
  }, [token]);

  // Launched from the Tools picker; the modals live here because the picker
  // closes when a sign-in opens.
  const signInAgain = useSignInAgain({ onConnected: fetchUserTools });

  useEffect(() => {
    if (isToolsPopupOpen) {
      fetchUserTools();
      (dispatch as AppDispatch)(loadConnectors({ token }));
    }
  }, [isToolsPopupOpen, fetchUserTools]);

  // Tools from a connected service sit under that service; the rest are
  // built in. Groups only appear once some tool comes from a connection.
  // A teammate's connection is never in the caller's list, so the tool's own
  // connection id decides, and the service is named from the catalog.
  const toolService = (tool: UserToolType) =>
    toolServiceOf(tool, connections, catalog);
  const anyConnectedTool = userTools.some((tool) => !!tool.connection_id);
  // Same groups as the agent builder: built in, one per service, then custom
  // tools (an API tool, an MCP server with no connection).
  const isCustomTool = (tool: UserToolType) =>
    !tool.connection_id &&
    (tool.name === 'api_tool' || tool.name === 'mcp_tool');
  const toolRank = (tool: UserToolType) =>
    tool.connection_id ? 1 : isCustomTool(tool) ? 2 : 0;
  const toolItems: MultiSelectPopoverItem[] = [...userTools]
    .sort((a, b) => toolRank(a) - toolRank(b))
    .map((tool) => {
      const service = toolService(tool);
      const connection = service?.connection;
      return {
        id: tool.id,
        label: tool.customName || tool.displayName,
        icon: service?.icon ? (
          <ConnectorIcon icon={service.icon} className="size-5" />
        ) : (
          <ToolIcon name={tool.name} className="size-5" />
        ),
        group: anyConnectedTool
          ? (service?.name ??
            (isCustomTool(tool)
              ? t('agents.form.toolsPopup.groupCustom')
              : t('settings.tools.groupBuiltIn')))
          : undefined,
        // Shared-by line; the sign-in warning below wins when both apply.
        description:
          !isOwner(tool) && tool.shared_via
            ? t('settings.tools.sharedBy', {
                interpolation: { escapeValue: false },
                team: tool.shared_via,
              })
            : undefined,
        descriptionNode: connectionNeedsSignIn(connection) ? (
          <p className="text-warning text-xs">
            {t('settings.connectors.health.signInAgain')}
          </p>
        ) : undefined,
      };
    });
  // Each broken connection once, with the tool it would re-sign (an MCP
  // preset keeps its tool rather than gaining a second one).
  const brokenConnections = connections
    .filter(connectionNeedsSignIn)
    .flatMap((connection) => {
      const tools = userTools.filter(
        (tool) => tool.connection_id === connection.id,
      );
      if (tools.length === 0) return [];
      const mcpTool = tools.find((tool) => tool.name === 'mcp_tool');
      return [{ connection, mcpToolId: mcpTool?.id }];
    });

  const selectedToolIds = userTools
    .filter((tool) => toolInChat(tool))
    .map((tool) => tool.id);

  // Ticks at once and unticks again when the server refuses it.
  const setToolInChat = (id: string, value: boolean) =>
    setUserTools((prev) =>
      prev.map((tool) =>
        tool.id !== id
          ? tool
          : isOwner(tool)
            ? { ...tool, status: value, in_chat: value }
            : { ...tool, in_chat: value },
      ),
    );

  const handleToggleTool = (id: string) => {
    const tool = userTools.find((t) => t.id === id);
    if (!tool) return;
    const newStatus = !toolInChat(tool);
    setToolInChat(id, newStatus);
    const fail = () => {
      setToolInChat(id, !newStatus);
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: t('settings.tools.statusUpdateFailed'),
        }),
      );
    };
    userService
      .updateToolStatus({ id, status: newStatus }, token)
      .then((response: Response) => {
        if (!response.ok) fail();
      })
      .catch((error: unknown) => {
        console.error('Failed to update tool status:', error);
        fail();
      });
  };

  const handleUploadClick = () => {
    setUploadModalState('ACTIVE');
    setIsSourcesPopupOpen(false);
  };

  // When ``allowSendWithoutText`` is set, an attachment-only submit is
  // permitted as long as at least one attachment can still go out; a
  // still-pending one arms the send instead of submitting (see handleSubmit).
  // A failed one doesn't count: it is dropped at submit time.
  const hasSubmittableContent =
    Boolean(value.trim()) ||
    (allowSendWithoutText && attachments.some((a) => a.status !== 'failed'));
  const composerIdle =
    !loading &&
    recordingState !== 'recording' &&
    recordingState !== 'transcribing';
  const canSubmit = hasSubmittableContent && composerIdle;

  const submitNow = () => {
    const failed = attachments.filter((a) => a.status === 'failed');
    const hasContent =
      Boolean(value.trim()) ||
      (allowSendWithoutText &&
        attachments.some((a) => a.status === 'completed'));
    // An attachment-only send whose files all failed has nothing left to
    // send; keep the failed chips so the user can see why.
    if (!hasContent) return;
    // A failed file will never succeed, so it must never cost the user their
    // question: drop it and send with whatever did upload.
    failed.forEach((a) => dispatch(removeAttachment(a.id)));
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
  };

  const {
    armed: sendArmed,
    readiness: sendReadiness,
    arm: armSend,
    cancel: cancelArmedSend,
  } = useArmedSend({
    attachments,
    onFlush: submitNow,
    // A queued send that settles while another answer streams would be
    // refused by the consumer after the composer was already cleared; hold
    // it until the composer can take a submit again.
    canFlush: composerIdle,
  });

  // Adopt a question queued outside the composer: seed the input, arm,
  // and hand the wait to the standard banner. If the attachments already
  // resolved by the time this runs, the armed-send effect flushes at once.
  useEffect(() => {
    if (queuedQuestion == null || queuedQuestion === '') return;
    setValue(queuedQuestion);
    armSend();
    onQueuedQuestionConsumed?.();
  }, [queuedQuestion]);

  const handleSubmit = () => {
    if (!canSubmit) return;
    // Attachments still uploading/parsing must never be silently dropped
    // from the payload: hold the send in the composer until every
    // attachment resolves, then flush automatically. Failed ones don't hold
    // it; submitNow drops them.
    if (sendReadiness.state !== 'ready') {
      armSend();
      return;
    }
    submitNow();
  };

  const handleCancel = () => {
    handleAbort();
  };

  const [draggingId, setDraggingId] = useState<string | null>(null);

  const handleAddToKnowledge = async () => {
    const completed = attachments.filter((a) => a.status === 'completed');
    const accepted = await knowledge.addToKnowledge(
      toSendableAttachments(completed),
    );
    // The files now belong to the Knowledge source; the upload toast shows
    // its progress and the source is selected for the chat once it is ready.
    if (accepted) completed.forEach((a) => dispatch(removeAttachment(a.id)));
  };

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

  return (
    <div {...getRootProps()} className="flex w-full flex-col">
      {signInAgain.modals}
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

      {/* translate="no": keep Chrome's page translator out of the composer —
          it rewrites text nodes into <font> wrappers and React loses the
          controls (dead Attach button, see AttachFileButton). */}
      <div
        translate="no"
        className="border-border bg-card relative flex w-full flex-col rounded-3xl border"
      >
        <AttachmentChipList
          attachments={attachments}
          draggingId={draggingId}
          onRemove={(id) => dispatch(removeAttachment(id))}
          onDragStart={handleDragStart}
          onDragOver={handleDragOver}
          onDropOn={handleDropOn}
          unreadableIds={unreadableAttachmentIds}
          modelName={selectedModel?.display_name}
        />

        {showSourceButton && overAttachmentBudget && (
          <KnowledgeHint
            readsRest={selectedModel?.supports_tools !== false}
            pending={knowledge.pending}
            error={knowledge.error}
            onAdd={() => {
              void handleAddToKnowledge();
            }}
          />
        )}

        {sendArmed && sendReadiness.state === 'waiting' && (
          <div
            className="text-muted-foreground flex items-center gap-2 px-2 pb-1 text-xs sm:px-3"
            role="status"
          >
            <span>
              {t('conversation.attachments.waitingToSend', {
                count: sendReadiness.pendingCount,
              })}
            </span>
            <Button
              type="button"
              variant="link"
              size="inline"
              onClick={cancelArmedSend}
              /* eslint-disable-next-line shadcn/no-restyle --
                 The queued-send Cancel sits inline in the composer's 12px status line; link inline keeps the base text-sm, so it takes the line's size. */
              className="text-xs"
            >
              {t('conversation.attachments.cancelQueuedSend')}
            </Button>
          </div>
        )}
        {voiceError && (
          <div className="text-destructive px-2 pb-1 text-xs sm:px-3">
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
            className="text-foreground placeholder:text-muted-foreground w-full resize-none overflow-x-hidden overflow-y-auto rounded-t-3xl bg-transparent px-2 text-base leading-tight whitespace-pre-wrap opacity-100 focus:outline-hidden sm:px-3"
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            aria-label={t('inputPlaceholder')}
          />
        </div>

        <div className="flex items-center px-2 pb-1.5 sm:px-3 sm:pb-2">
          <div className="flex grow flex-wrap gap-1 sm:gap-2">
            {showSourceButton && (
              <SourcesTrigger
                open={isSourcesPopupOpen}
                onOpenChange={setIsSourcesPopupOpen}
                items={sourceItems}
                selectedIds={selectedSourceIds}
                onToggle={handleToggleSource}
                selectedDocs={selectedDocs}
                onUploadClick={handleUploadClick}
              />
            )}

            {showToolButton && (
              <ToolsTrigger
                open={isToolsPopupOpen}
                onOpenChange={setIsToolsPopupOpen}
                items={toolItems}
                selectedIds={selectedToolIds}
                onToggle={handleToggleTool}
                loading={toolsLoading}
                notice={
                  <SignInAgainNotice
                    connections={brokenConnections.map(
                      ({ connection }) => connection,
                    )}
                    onReconnect={(connection) => {
                      setIsToolsPopupOpen(false);
                      signInAgain.reconnect(
                        connection,
                        brokenConnections.find(
                          (entry) => entry.connection.id === connection.id,
                        )?.mcpToolId,
                      );
                    }}
                  />
                }
              />
            )}
            {ENABLE_VOICE_INPUT && sttAvailable && (
              <MicButton
                recordingState={recordingState}
                loading={loading}
                onClick={() => {
                  void handleVoiceInput();
                }}
              />
            )}
            <AttachFileButton onChange={handleFileAttachment} />
            {/* Additional badges can be added here in the future */}
          </div>

          {loading ? (
            <IconButton
              label={t('cancel')}
              variant="default"
              size="icon"
              shape="pill"
              onClick={handleCancel}
              className="ml-auto size-7 shrink-0 sm:size-9"
              disabled={!loading}
            >
              <div className="flex size-3 items-center justify-center rounded-sm bg-white sm:size-3.5" />
            </IconButton>
          ) : (
            <IconButton
              label={t('conversation.send')}
              variant="default"
              size="icon"
              shape="pill"
              onClick={handleSubmit}
              className={cn(
                'ml-auto size-7 shrink-0 sm:size-9',
                !canSubmit &&
                  /* eslint-disable-next-line shadcn/no-restyle --
                     The empty composer's send button is a grey circle, not a
                     faded brand one: no variant is neutral while disabled, and
                     secondary is the brand-tinted pressed state. */
                  'bg-muted text-muted-foreground dark:bg-accent',
              )}
              disabled={!canSubmit}
            >
              <SendArrow
                className="mx-auto my-auto block size-3.5 sm:size-4"
                aria-hidden="true"
              />
            </IconButton>
          )}
        </div>
      </div>

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
          <div className="bg-background/85 pointer-events-none fixed top-0 left-0 z-50 flex size-full flex-col items-center justify-center">
            <CloudUpload className="size-18" />
            <span className="text-foreground px-2 text-xl leading-tight font-semibold">
              {t('modals.uploadDoc.drag.title')}
            </span>
            <span className="text-muted-foreground w-48 p-2 text-center text-sm">
              {t('modals.uploadDoc.drag.description')}
            </span>
          </div>,
          document.body,
        )}
    </div>
  );
}
