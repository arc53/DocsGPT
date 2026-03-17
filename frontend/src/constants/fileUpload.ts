export const AUDIO_FILE_ACCEPT: Record<string, string[]> = {
  'audio/mpeg': ['.mp3'],
  'audio/mp4': ['.m4a'],
  'audio/ogg': ['.ogg'],
  'audio/wav': ['.wav'],
  'audio/webm': ['.webm'],
  'video/webm': ['.webm'],
};

export const FILE_UPLOAD_ACCEPT: Record<string, string[]> = {
  'application/pdf': ['.pdf'],
  'text/plain': ['.txt'],
  'text/x-rst': ['.rst'],
  'text/x-markdown': ['.md'],
  'application/zip': ['.zip'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': [
    '.docx',
  ],
  'application/json': ['.json'],
  'text/csv': ['.csv'],
  'text/html': ['.html'],
  'application/epub+zip': ['.epub'],
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': [
    '.xlsx',
  ],
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': [
    '.pptx',
  ],
  'image/png': ['.png'],
  'image/jpeg': ['.jpeg'],
  'image/jpg': ['.jpg'],
  ...AUDIO_FILE_ACCEPT,
};

export const FILE_UPLOAD_ACCEPT_ATTR = [
  '.pdf',
  '.txt',
  '.rst',
  '.md',
  '.zip',
  '.docx',
  '.json',
  '.csv',
  '.html',
  '.epub',
  '.xlsx',
  '.pptx',
  '.png',
  '.jpeg',
  '.jpg',
  '.wav',
  '.mp3',
  '.m4a',
  '.ogg',
  '.webm',
].join(',');

export const SOURCE_FILE_TREE_ACCEPT_ATTR = [
  '.rst',
  '.md',
  '.pdf',
  '.txt',
  '.docx',
  '.csv',
  '.epub',
  '.html',
  '.mdx',
  '.json',
  '.xlsx',
  '.pptx',
  '.png',
  '.jpg',
  '.jpeg',
].join(',');
