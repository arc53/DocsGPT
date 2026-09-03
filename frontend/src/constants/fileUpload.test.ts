import { describe, expect, it } from 'vitest';

import {
  ATTACHMENT_FILE_ACCEPT_ATTR,
  ATTACHMENT_PARSER_EXTENSIONS,
  getFileExtension,
  hasAttachmentParser,
  looksLikeText,
  parseUploadErrorMessage,
  parseUploadErrorsByIndex,
  partitionAttachmentFiles,
} from './fileUpload';

const file = (name: string, body: BlobPart = 'x', type = '') =>
  new File([body], name, { type });

const bytes = (...values: number[]) => new Uint8Array(values);

const MP4_HEADER = bytes(
  0x00,
  0x00,
  0x00,
  0x18,
  0x66,
  0x74,
  0x79,
  0x70,
  0x69,
  0x73,
  0x6f,
  0x6d,
);

describe('attachment type gate', () => {
  it('extracts a lower-cased extension', () => {
    expect(getFileExtension('Photo.JPG')).toBe('.jpg');
    expect(getFileExtension('a.tar.gz')).toBe('.gz');
    expect(getFileExtension('noext')).toBe('');
    expect(getFileExtension('.env')).toBe('');
  });

  it('recognises parser-backed suffixes by name, case-insensitively', () => {
    expect(hasAttachmentParser(file('Report.PDF'))).toBe(true);
    expect(hasAttachmentParser(file('scan.WebP'))).toBe(true);
    expect(hasAttachmentParser(file('subs.vtt'))).toBe(true);
    // No parser — these are judged on content, not on the suffix.
    expect(hasAttachmentParser(file('main.py'))).toBe(false);
    expect(hasAttachmentParser(file('archive.zip'))).toBe(false);
    expect(hasAttachmentParser(file('clip.mp4'))).toBe(false);
    // .txt is the plain-text fallthrough itself, not a parser.
    expect(hasAttachmentParser(file('notes.txt'))).toBe(false);
  });

  it('mirrors the backend list: no zip, no video, images and markup included', () => {
    expect(ATTACHMENT_PARSER_EXTENSIONS).toContain('.pdf');
    // Parser-backed suffixes the first cut of this list missed.
    for (const ext of [
      '.webp',
      '.tiff',
      '.tif',
      '.bmp',
      '.vtt',
      '.xml',
      '.mdx',
    ]) {
      expect(ATTACHMENT_PARSER_EXTENSIONS).toContain(ext);
    }
    expect(ATTACHMENT_PARSER_EXTENSIONS).not.toContain('.zip');
    expect(ATTACHMENT_PARSER_EXTENSIONS).not.toContain('.mp4');
    expect(ATTACHMENT_PARSER_EXTENSIONS).not.toContain('.txt');
  });

  it('never hides a file the upload would accept behind the picker filter', () => {
    const listed = ATTACHMENT_FILE_ACCEPT_ATTR.split(',');
    for (const ext of ATTACHMENT_PARSER_EXTENSIONS) {
      expect(listed).toContain(ext);
    }
    // Parserless text (.txt, .py, .log) is accepted on content, so the
    // picker must not filter it out.
    expect(listed).toContain('.txt');
    expect(listed).toContain('text/*');
  });
});

describe('looksLikeText', () => {
  it('accepts empty, plain, accented and ANSI-coloured text', () => {
    expect(looksLikeText(new Uint8Array())).toBe(true);
    expect(looksLikeText(new TextEncoder().encode('plain text\n'))).toBe(true);
    expect(looksLikeText(new TextEncoder().encode('café — em dash\n'))).toBe(
      true,
    );
    expect(looksLikeText(bytes(0x1b, 0x5b, 0x33, 0x31, 0x6d, 0x6f, 0x6b))).toBe(
      true,
    );
  });

  it('accepts BOM-marked Unicode, which is half NUL bytes but still text', () => {
    // UTF-8, UTF-16 LE/BE, and UTF-32 BE (no TextDecoder — left to the server).
    expect(looksLikeText(bytes(0xef, 0xbb, 0xbf, 0x68, 0x69))).toBe(true);
    expect(looksLikeText(bytes(0xff, 0xfe, 0x68, 0x00, 0x69, 0x00))).toBe(true);
    expect(looksLikeText(bytes(0xfe, 0xff, 0x00, 0x68, 0x00, 0x69))).toBe(true);
    expect(looksLikeText(bytes(0x00, 0x00, 0xfe, 0xff, 0x00, 0x68))).toBe(true);
  });

  it('still rejects binary behind a BOM — three bytes buy nothing', () => {
    // UTF-8 BOM + MP4 header: the byte rules apply to what follows it.
    expect(looksLikeText(bytes(0xef, 0xbb, 0xbf, ...MP4_HEADER))).toBe(false);
    // UTF-16 LE BOM + control-only code points.
    expect(
      looksLikeText(
        bytes(0xff, 0xfe, 0x01, 0x00, 0x02, 0x00, 0x03, 0x00, 0x04, 0x00),
      ),
    ).toBe(false);
    // UTF-16 BE BOM + bytes that decode to NUL characters.
    expect(looksLikeText(bytes(0xfe, 0xff, 0x00, 0x00, 0x00, 0x41))).toBe(
      false,
    );
  });

  it('rejects a NUL byte and dense control bytes', () => {
    expect(looksLikeText(MP4_HEADER)).toBe(false);
    expect(looksLikeText(bytes(0x74, 0x78, 0x00, 0x74))).toBe(false);
    expect(
      looksLikeText(
        new Uint8Array(Array.from({ length: 64 }, (_, i) => i + 1)),
      ),
    ).toBe(false);
  });
});

describe('partitionAttachmentFiles', () => {
  it('refuses video and archives whatever the picker claims the type is', async () => {
    const { supported, unsupported } = await partitionAttachmentFiles([
      file('clip.mp4', MP4_HEADER, 'text/plain'),
      file('archive.zip', bytes(0x50, 0x4b, 0x03, 0x04, 0x00, 0x00)),
    ]);
    expect(supported).toEqual([]);
    expect(unsupported.map((f) => f.name)).toEqual(['clip.mp4', 'archive.zip']);
  });

  it('keeps text files that have no parser — the backend reads them', async () => {
    const { supported, unsupported } = await partitionAttachmentFiles([
      file('notes.txt', 'plain\n'),
      file('main.py', 'def main():\n    return 1\n'),
      file('server.log', '2026-09-02 ERROR boom\n'),
      file('Dockerfile', 'FROM python:3.12\n'),
    ]);
    expect(supported.map((f) => f.name)).toEqual([
      'notes.txt',
      'main.py',
      'server.log',
      'Dockerfile',
    ]);
    expect(unsupported).toEqual([]);
  });

  it('refuses a binary renamed to .txt — .txt is sniffed like any other suffix', async () => {
    const { supported, unsupported } = await partitionAttachmentFiles([
      file('notes.txt', MP4_HEADER),
      // A BOM in front of it changes nothing.
      file('bom.txt', bytes(0xef, 0xbb, 0xbf, ...MP4_HEADER)),
    ]);
    expect(supported).toEqual([]);
    expect(unsupported.map((f) => f.name)).toEqual(['notes.txt', 'bom.txt']);
  });

  it('admits parser-backed types on their suffix, binary contents and all', async () => {
    // A PDF is binary; the sniff must never be applied to it.
    const { supported, unsupported } = await partitionAttachmentFiles([
      file('paper.pdf', MP4_HEADER),
      file('photo.jpeg', MP4_HEADER),
    ]);
    expect(supported.map((f) => f.name)).toEqual(['paper.pdf', 'photo.jpeg']);
    expect(unsupported).toEqual([]);
  });

  it('partitions a mixed selection and keeps the original order', async () => {
    const mp4 = file('clip.mp4', MP4_HEADER);
    const txt = file('notes.txt');
    const pdf = file('paper.pdf');
    const { supported, unsupported } = await partitionAttachmentFiles([
      mp4,
      txt,
      pdf,
    ]);
    expect(supported).toEqual([txt, pdf]);
    expect(unsupported).toEqual([mp4]);
  });
});

describe('parseUploadErrorMessage', () => {
  it('returns the server message when present', () => {
    expect(
      parseUploadErrorMessage(
        '{"success":false,"message":"Unsupported file type: .mp4"}',
      ),
    ).toBe('Unsupported file type: .mp4');
  });

  it('returns undefined for non-JSON bodies or a missing message', () => {
    expect(parseUploadErrorMessage('<html>502</html>')).toBeUndefined();
    expect(parseUploadErrorMessage('{"ok":1}')).toBeUndefined();
    expect(parseUploadErrorMessage('')).toBeUndefined();
  });
});

describe('parseUploadErrorsByIndex', () => {
  it('keys each reason by its upload_index', () => {
    const byIndex = parseUploadErrorsByIndex(
      JSON.stringify({
        success: false,
        message: 'Unsupported file type: .mp4',
        errors: [
          {
            upload_index: 0,
            filename: 'clip.mp4',
            error: 'Unsupported file type: .mp4',
          },
          {
            upload_index: 1,
            filename: 'a.zip',
            error: 'Unsupported file type: .zip',
          },
        ],
      }),
    );
    // Without this, both chips would repeat the first file's reason.
    expect(byIndex.get(0)).toBe('Unsupported file type: .mp4');
    expect(byIndex.get(1)).toBe('Unsupported file type: .zip');
  });

  it('is empty for bodies with no usable errors array', () => {
    expect(parseUploadErrorsByIndex('<html>502</html>').size).toBe(0);
    expect(parseUploadErrorsByIndex('{"message":"nope"}').size).toBe(0);
    expect(parseUploadErrorsByIndex('').size).toBe(0);
    expect(
      parseUploadErrorsByIndex('{"errors":[{"error":"no index"}]}').size,
    ).toBe(0);
  });
});
