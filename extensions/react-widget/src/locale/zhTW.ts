import type { Messages } from './en';

/** Traditional Chinese. Keys and their context are in `en.ts`. */
export const zhTW = {
  launcherButton: '提問',
  headerTitle: '取得 AI 協助',
  headerDescription: 'DocsGPT 的 AI 聊天機器人隨時為您提供協助',
  heroTitle: '歡迎使用 DocsGPT！',
  heroDescription:
    '此聊天機器人以 DocsGPT 打造，並使用生成式 AI，請透過來源查證重要資訊。',
  suggestedQuestions: '建議問題',
  expandChat: '展開對話',
  collapseChat: '收合對話',
  closeChat: '關閉對話',
  newChat: 'New chat', // TODO(translate)
  chatHistory: 'Chat history', // TODO(translate)
  historyHeading: 'History', // TODO(translate)
  backToChat: 'Back to chat', // TODO(translate)
  historyToday: 'Today', // TODO(translate)
  historyYesterday: 'Yesterday', // TODO(translate)
  historyPrevious7Days: 'Previous 7 days', // TODO(translate)
  historyOlder: 'Older', // TODO(translate)
  historyEmpty: 'Your conversations will appear here.', // TODO(translate)
  deleteConversation: 'Delete conversation', // TODO(translate)
  clearAll: 'Clear all', // TODO(translate)
  clearAllConfirm: 'Delete all saved conversations?', // TODO(translate)
  clearAllConfirmButton: 'Delete all', // TODO(translate)
  cancel: 'Cancel', // TODO(translate)
  sources: '來源',
  openSource: '開啟來源 {number}',
  toolsUsed: '已使用 {tools}',
  thinking: '思考中…',
  generating: '產生中…',
  runningCode: '正在執行程式碼…',
  decidingNextStep: '正在決定下一步…',
  workflowStep: '{step}…',
  copyAnswer: '複製回答',
  copyCode: '複製程式碼',
  copied: '已複製',
  goodResponse: '回答很好',
  badResponse: '回答不好',
  feedbackNotSaved: '無法儲存',
  answerFailed: '無法產生回覆',
  connectionError: '發生錯誤。請檢查網路連線後再試一次。',
  interrupted: 'This answer was interrupted before it finished.', // TODO(translate)
  retry: '重試',
  copyError: '複製錯誤訊息',
  scrollToLatest: '捲動至最新訊息',
  composerPlaceholder: '輸入您的問題',
  sendMessage: '傳送訊息',
  stopGenerating: '停止產生',
  waitingForFiles_one: '正在等候 {count} 個檔案處理完成…',
  waitingForFiles_other: '正在等候 {count} 個檔案處理完成…',
  removeFailedFile: '請先移除無法附加的檔案，再傳送。',
  stopDictatingToSend: '請先停止語音輸入，再傳送問題。',
  dropFiles: '拖放檔案以附加',
  attachFiles: '附加檔案',
  attach: '附件',
  uploading: '正在上傳 {percent}%',
  processing: '正在處理',
  ready: '已就緒',
  failed: '失敗',
  removeFile: '移除 {name}',
  fileUnreadable: '無法讀取此檔案。',
  fileTooSlow: '處理時間過長。',
  fileTypeRejected: '此處不接受 {extension} 檔案。',
  fileTypeUnknownRejected: '此處不接受該檔案類型。',
  uploadFailed: '上傳失敗。',
  uploadTimedOut: '上傳逾時。',
  micVoice: '語音',
  micStop: '停止',
  micTranscribing: '轉錄中',
  voiceInput: '語音輸入',
  stopRecording: '停止錄音',
  transcribingAudio: '正在轉錄音訊',
  listening: '聆聽中…',
  finishing: '即將完成…',
  voiceNoSpeech: '未偵測到語音。',
  voiceBlocked: '麥克風存取遭到封鎖。',
  voiceNoMicrophone: '找不到麥克風。',
  voiceUnavailable: '語音輸入目前無法使用。',
  voiceLanguageUnsupported: '語音輸入不支援此語言。',
  voiceStopped: '語音輸入意外停止。',
  voiceNeedsHttps: '語音輸入需要安全連線（HTTPS）。',
  voiceUnsupported: '此瀏覽器不支援語音輸入。',
  poweredBy: '由 {brand} 提供技術支援',
  searchPlaceholder: '搜尋或詢問 AI…',
  searchButton: '在此搜尋',
  ctrlKey: 'Ctrl',
  askTheAi: '詢問 AI',
  searching: '正在搜尋…',
  searchFailed: '搜尋失敗。您仍可詢問 AI。',
  noResults: '找不到結果',
} satisfies Messages;
