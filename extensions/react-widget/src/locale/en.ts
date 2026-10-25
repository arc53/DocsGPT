/**
 * The widget's UI text in English, and the source of truth for every other
 * locale. Each key's comment says where the string appears and, for buttons
 * and labels, how much room it has.
 *
 * `{name}` is replaced at runtime; keep it in the translation. Keys ending in
 * `_one` / `_other` are plural forms picked by `Intl.PluralRules`; a locale
 * that needs more forms adds `_zero`, `_two`, `_few` or `_many` next to them.
 */
export const en = {
  // Floating launcher button, bottom right. Short: about 20 characters.
  launcherButton: 'Ask a question',
  // Chat header title. About 30 characters.
  headerTitle: 'Get AI assistance',
  // Chat header subtitle under the title. One short line.
  headerDescription: "DocsGPT's AI Chatbot is here to help",
  // Welcome card title before the first message. About 30 characters.
  heroTitle: 'Welcome to DocsGPT !',
  // Welcome card text; clamped to three lines.
  heroDescription:
    'This chatbot is built with DocsGPT and utilises GenAI, please review important information using sources.',
  // Small heading above the suggested-question buttons. About 30 characters.
  suggestedQuestions: 'Suggested questions',
  // Header icon button (screen readers and tooltip): enlarge the panel.
  expandChat: 'Expand chat',
  // Header icon button: shrink the enlarged panel back.
  collapseChat: 'Collapse chat',
  // Header icon button: close the chat panel.
  closeChat: 'Close chat',
  // The docked sidebar's inner edge (screen readers): drag it or use the arrow keys to change the width.
  resizeSidebar: 'Resize chat',
  // Header icon button (screen readers and tooltip): clear the chat and start over.
  newChat: 'New chat',
  // Header icon button (screen readers and tooltip): show the saved conversations.
  chatHistory: 'Chat history',

  // Heading of the saved-conversations view, which replaces the messages. One short word.
  historyHeading: 'History',
  // Icon button beside that heading (screen readers and tooltip): leave the list.
  backToChat: 'Back to chat',
  // Group label in the list: conversations from today.
  historyToday: 'Today',
  // Group label in the list: conversations from yesterday.
  historyYesterday: 'Yesterday',
  // Group label in the list: conversations from the week before yesterday.
  historyPrevious7Days: 'Previous 7 days',
  // Group label in the list: anything older than a week.
  historyOlder: 'Older',
  // Shown instead of the list when nothing is saved. One calm sentence.
  historyEmpty: 'Your conversations will appear here.',
  // Trash icon button on a row (screen readers and tooltip); the row's title is read after it.
  deleteConversation: 'Delete conversation',
  // Small text button beside the heading: delete every saved conversation. About 12 characters.
  clearAll: 'Clear all',
  // Confirmation question that replaces the list's top row after "Clear all".
  clearAllConfirm: 'Delete all saved conversations?',
  // Destructive button in that confirmation. About 12 characters.
  clearAllConfirmButton: 'Delete all',
  // Button in that confirmation that keeps the conversations. About 12 characters.
  cancel: 'Cancel',

  // Toggle above an answer that lists its sources, followed by a count. One word.
  sources: 'Sources',
  // Pill on a citation number in an answer (screen readers and tooltip).
  openSource: 'Open source {number}',
  // Status line under an answer naming the tools the agent ran; {tools} is a list of tool names.
  toolsUsed: 'Used {tools}',
  // Status line while the answer has not started. Ends with an ellipsis.
  thinking: 'Thinking…',
  // Status line while the answer streams in. Ends with an ellipsis.
  generating: 'Generating…',
  // Status line while a workflow runs a code step. Ends with an ellipsis.
  runningCode: 'Running code…',
  // Status line while a workflow picks its next branch. Ends with an ellipsis.
  decidingNextStep: 'Deciding next step…',
  // Status line for a named workflow step; {step} is the step's own name.
  workflowStep: '{step}…',

  // Icon button under an answer (screen readers): copy the answer text.
  copyAnswer: 'Copy answer',
  // Icon button under a code block in an answer (screen readers).
  copyCode: 'Copy code',
  // Hidden text read after an answer link (screen readers only).
  opensInNewTab: 'Opens in a new tab',
  // The copy button's label for a moment after copying.
  copied: 'Copied',
  // Thumbs-up icon button under an answer (screen readers).
  goodResponse: 'Good response',
  // Thumbs-down icon button under an answer (screen readers).
  badResponse: 'Bad response',
  // Small red note beside the thumbs when the rating failed to save. About 15 characters.
  feedbackNotSaved: "Couldn't save",

  // Title of the red alert shown instead of an answer.
  answerFailed: "Couldn't generate a response",
  // Alert text when the request itself failed (network or server down).
  connectionError: 'Something went wrong. Check your connection and try again.',
  // Alert text for an answer that was still arriving when the page was closed or reloaded.
  interrupted: 'This answer was interrupted before it finished.',
  // Icon button under a failed answer (screen readers): ask again.
  retry: 'Retry',
  // Icon button under a failed answer (screen readers): copy the error text.
  copyError: 'Copy error',
  // Round button that appears when scrolled up (screen readers).
  scrollToLatest: 'Scroll to latest message',

  // Message box placeholder, also its accessible name. About 25 characters.
  composerPlaceholder: 'Ask your question',
  // Send button (screen readers).
  sendMessage: 'Send message',
  // Stop button that replaces Send while an answer streams (screen readers).
  stopGenerating: 'Stop generating',
  // Note under the message box while files upload; {count} is the number of files.
  waitingForFiles_one: 'Waiting for {count} file to finish…',
  waitingForFiles_other: 'Waiting for {count} files to finish…',
  // Note under the message box when an attachment failed.
  removeFailedFile: 'Remove the file that could not be attached, then send.',
  // Tooltip on the suggested questions while dictation runs.
  stopDictatingToSend: 'Stop dictating to send a question.',
  // Centred over the panel while files are dragged onto it. About 25 characters.
  dropFiles: 'Drop files to attach',

  // Attach button (screen readers).
  attachFiles: 'Attach files',
  // Attach button's visible text, beside a paperclip. One short word.
  // At the small size it shares a ~210px row with the microphone button's text
  // (micVoice, micStop, micTranscribing), so keep them all short.
  attach: 'Attach',
  // Attachment chip tooltip while uploading; {percent} is 0–100.
  uploading: 'Uploading {percent}%',
  // Attachment chip tooltip while the server reads the file.
  processing: 'Processing',
  // Attachment chip tooltip once the file is ready to send.
  ready: 'Ready',
  // Attachment chip tooltip when it failed without a reason.
  failed: 'Failed',
  // X button on an attachment chip (screen readers); {name} is the file name.
  removeFile: 'Remove {name}',
  // Attachment error: the server could not parse the file.
  fileUnreadable: 'Could not read this file.',
  // Attachment error: parsing ran past its time limit.
  fileTooSlow: 'Took too long to process.',
  // Attachment error for a rejected type; {extension} is like ".exe".
  fileTypeRejected: '{extension} is not accepted here.',
  // Attachment error for a rejected file with no extension.
  fileTypeUnknownRejected: 'That file type is not accepted here.',
  // Attachment error: the upload request failed.
  uploadFailed: 'Upload failed.',
  // Attachment error: the upload request timed out.
  uploadTimedOut: 'Upload timed out.',

  // Microphone button's visible text, idle. One short word. Shares a ~210px
  // row with `attach` at the small size.
  micVoice: 'Voice',
  // Microphone button's visible text while recording. One short word; shares
  // the row with `attach`.
  micStop: 'Stop',
  // Microphone button's visible text while the last words are processed. One
  // word; shares the row with `attach`.
  micTranscribing: 'Transcribing',
  // Microphone button (screen readers), idle.
  voiceInput: 'Voice input',
  // Microphone button (screen readers) while recording.
  stopRecording: 'Stop recording',
  // Microphone button (screen readers) while the last words are processed.
  transcribingAudio: 'Transcribing audio',
  // Shown beside the waveform while recording. Ends with an ellipsis.
  listening: 'Listening…',
  // Shown beside the waveform after stop, until the text arrives.
  finishing: 'Finishing…',
  // Dictation error.
  voiceNoSpeech: 'No speech was picked up.',
  // Dictation error.
  voiceBlocked: 'Microphone access was blocked.',
  // Dictation error.
  voiceNoMicrophone: 'No microphone was found.',
  // Dictation error: the browser's speech service is unreachable.
  voiceUnavailable: 'Voice input is unavailable right now.',
  // Dictation error: the speech service does not support the page language.
  voiceLanguageUnsupported: 'Voice input does not support this language.',
  // Dictation error, for any other failure.
  voiceStopped: 'Voice input stopped unexpectedly.',
  // Dictation error on a plain-HTTP page.
  voiceNeedsHttps: 'Voice input needs a secure connection (HTTPS).',
  // Dictation error in a browser without speech recognition.
  voiceUnsupported: 'This browser does not support voice input.',

  // Credit line under the chat and search results; {brand} is the linked product
  // name. Without {brand} the line is plain text with no link.
  poweredBy: 'Powered by {brand}',

  // Search field placeholder and the search dialog's accessible name. About 25 characters.
  searchPlaceholder: 'Search or Ask AI...',
  // Text on the search button and the dropdown field. About 20 characters.
  searchButton: 'Search here',
  // Control key name in the search button's shortcut hint, e.g. "Ctrl K". Use the label on local keyboards.
  ctrlKey: 'Ctrl',
  // First row of the search results: opens the chat with the query. About 15 characters.
  askTheAi: 'Ask the AI',
  // Search results status while loading. Ends with an ellipsis.
  searching: 'Searching…',
  // Search results status when the search request failed.
  searchFailed: "Search didn't work. You can still ask the AI.",
  // Search results status when nothing matched.
  noResults: 'No results found',
};

/** Plural forms beyond `_one` / `_other` that some languages need. */
type ExtraPluralForms<K> = K extends `${infer Base}_other`
  ? `${Base}_${'zero' | 'two' | 'few' | 'many'}`
  : never;

/** Every UI string the widget shows, keyed as in the English catalogue. */
export type Messages = { [K in keyof typeof en]: string } & {
  [K in ExtraPluralForms<keyof typeof en>]?: string;
};

/** A key with plural forms, without its `_one` / `_other` suffix. */
export type PluralKey = keyof typeof en extends infer K
  ? K extends `${infer Base}_other`
    ? Base
    : never
  : never;
