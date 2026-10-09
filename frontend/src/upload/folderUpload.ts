import { getFileExtension } from '../constants/fileUpload';

/**
 * Where a picked file sits inside the folder it came from, as `/`-joined
 * parts. The folder picker sets `webkitRelativePath` (`docs/guide/a.md`);
 * react-dropzone sets `path` on dropped files (`/docs/guide/a.md` from a
 * dropped folder, `./a.md` for a loose file). A loose file gives one part.
 */
function pathParts(file: File): string[] {
  const { path } = file as File & { path?: string };
  const raw = file.webkitRelativePath || path || '';
  const parts = raw
    .split(/[\\/]/)
    .filter((part) => part !== '' && part !== '.' && part !== '..');
  return parts.length > 0 ? parts : [file.name];
}

/**
 * The name a file is uploaded under: its path inside the dropped or picked
 * folder, or just its name. The backend keeps that path under the source.
 */
export function getUploadPath(file: File): string {
  return pathParts(file).join('/');
}

/** The top folder a file came from, or undefined for a loose file. */
export function getFolderName(file: File): string | undefined {
  const parts = pathParts(file);
  return parts.length > 1 ? parts[0] : undefined;
}

/**
 * Whether the file or one of its folders is hidden (`.git`, `.DS_Store`).
 * The worker skips hidden files, so a folder's are left out quietly rather
 * than listed as rejected.
 */
export function isHiddenUpload(file: File): boolean {
  return pathParts(file).some((part) => part.startsWith('.'));
}

/** Whether the file's extension is one the upload accepts. */
export function hasAcceptedExtension(
  file: File,
  accept: Record<string, string[]>,
): boolean {
  const extension = getFileExtension(file.name);
  return extension !== '' && Object.values(accept).flat().includes(extension);
}
