import mermaid from 'mermaid';
import { Download, FileText, History, RotateCcw } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { useDarkTheme } from '../hooks';
import { selectToken } from '../preferences/preferenceSlice';
import Spinner from './Spinner';
import {
  buildPreviewDocument,
  displayFilename,
  findCurrentVersion,
  formatBytes,
  previewModeForKind,
  sortVersionsDesc,
  triggerResponseDownload,
  type ArtifactVersion,
  type DocumentArtifact,
} from './artifactViewUtils';
import { Button } from './ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from './ui/select';

function asPreviewString(spec: unknown): string {
  if (typeof spec === 'string') return spec;
  if (spec && typeof spec === 'object') {
    const rec = spec as Record<string, unknown>;
    for (const key of ['html', 'svg', 'content', 'source', 'code']) {
      if (typeof rec[key] === 'string') return rec[key] as string;
    }
  }
  return '';
}

function FramePreview({
  artifactKind,
  source,
}: {
  artifactKind: string;
  source: string;
}) {
  const [isDarkTheme] = useDarkTheme();
  const [rendered, setRendered] = useState<string | null>(null);
  const [renderError, setRenderError] = useState(false);
  const isMermaid = artifactKind.toLowerCase() === 'mermaid';

  // `securityLevel: 'sandbox'` makes mermaid build the diagram's live DOM inside
  // its OWN opaque-origin `sandbox=""` iframe (not the app document) and return
  // an `<iframe src="data:text/html;base64,…">` wrapper, so untrusted diagram
  // text never becomes live nodes in the app origin. The wrapper is embedded
  // into the outer scriptless `sandbox=""` preview iframe below.
  useEffect(() => {
    if (!isMermaid) {
      setRendered(source);
      return;
    }
    let cancelled = false;
    setRendered(null);
    setRenderError(false);
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'sandbox',
      theme: isDarkTheme ? 'dark' : 'default',
    });
    mermaid
      .render(`artifact-mermaid-${Date.now()}`, source)
      .then(({ svg }) => {
        if (!cancelled) setRendered(svg);
      })
      .catch(() => {
        if (!cancelled) setRenderError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [isMermaid, source, isDarkTheme]);

  if (renderError) {
    return (
      <pre className="overflow-auto p-4 text-xs text-gray-600 dark:text-gray-400">
        {source}
      </pre>
    );
  }
  if (rendered === null) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }

  // For mermaid, `rendered` is mermaid's sandboxed-iframe wrapper; the 'mermaid'
  // preview document carries a CSP that permits its inner `data:` frame.
  const previewKind = isMermaid ? 'mermaid' : artifactKind;
  return (
    <iframe
      // No allow-same-origin: content is fully isolated from the app origin.
      sandbox=""
      title="Artifact preview"
      className="h-full w-full rounded-md border border-gray-200 bg-white dark:border-gray-700"
      srcDoc={buildPreviewDocument(previewKind, rendered)}
    />
  );
}

function DownloadCard({
  filename,
  size,
  onDownload,
  downloading,
}: {
  filename: string;
  size: number | null;
  onDownload: () => void;
  downloading: boolean;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4">
      <div className="flex flex-col items-center gap-3 rounded-xl border border-gray-200 p-8 text-center dark:border-gray-700">
        <FileText className="h-12 w-12 text-gray-400" />
        <div>
          <p className="text-sm font-medium break-all text-gray-800 dark:text-gray-200">
            {filename}
          </p>
          {size != null && (
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {formatBytes(size)}
            </p>
          )}
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onDownload}
          disabled={downloading}
        >
          {downloading ? (
            <Spinner size="small" />
          ) : (
            <Download className="h-4 w-4" />
          )}
          Download
        </Button>
      </div>
    </div>
  );
}

export default function DocumentArtifactView({
  artifact,
  onRefresh,
}: {
  artifact: DocumentArtifact;
  onRefresh: () => void;
}) {
  const token = useSelector(selectToken);
  const versionsDesc = useMemo(
    () => sortVersionsDesc(artifact.versions),
    [artifact.versions],
  );
  const [selectedVersion, setSelectedVersion] = useState<number>(
    artifact.current_version,
  );
  const [downloading, setDownloading] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Guards async setState after the sidebar closes mid-request (the download /
  // restore promises can resolve after unmount), mirroring the sidebar's
  // currentFetchIdRef discipline.
  const isMountedRef = useRef(true);
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    setSelectedVersion(artifact.current_version);
  }, [artifact.id, artifact.current_version]);

  const selectedRow: ArtifactVersion | null = useMemo(() => {
    return (
      artifact.versions.find((v) => v.version === selectedVersion) ??
      findCurrentVersion(artifact)
    );
  }, [artifact, selectedVersion]);

  const isCurrent = selectedVersion === artifact.current_version;
  const mode = previewModeForKind(artifact.kind, selectedRow?.mime_type);
  const filename = displayFilename(artifact, selectedRow);

  const handleDownload = async () => {
    setActionError(null);
    setDownloading(true);
    try {
      const response = await userService.downloadArtifact(
        artifact.id,
        token,
        selectedVersion,
      );
      const ok = await triggerResponseDownload(response, filename);
      if (!ok && isMountedRef.current) setActionError('Download failed');
    } catch {
      if (isMountedRef.current) setActionError('Download failed');
    } finally {
      if (isMountedRef.current) setDownloading(false);
    }
  };

  const handleRestore = async () => {
    setActionError(null);
    setRestoring(true);
    try {
      const response = await userService.restoreArtifactVersion(
        artifact.id,
        selectedVersion,
        token,
      );
      if (!response.ok) {
        if (isMountedRef.current) setActionError('Restore failed');
        return;
      }
      if (isMountedRef.current) onRefresh();
    } catch {
      if (isMountedRef.current) setActionError('Restore failed');
    } finally {
      if (isMountedRef.current) setRestoring(false);
    }
  };

  const renderPreview = () => {
    if (mode === 'frame') {
      const source = asPreviewString(
        isCurrent ? artifact.spec : selectedRow?.preview_text,
      );
      if (!source) {
        return (
          <p className="p-4 text-sm text-gray-500 dark:text-gray-400">
            No preview for this version.
          </p>
        );
      }
      return <FramePreview artifactKind={artifact.kind} source={source} />;
    }
    if (mode === 'image') {
      return (
        <DownloadCard
          filename={filename}
          size={selectedRow?.size ?? null}
          onDownload={handleDownload}
          downloading={downloading}
        />
      );
    }
    if (mode === 'card') {
      return (
        <DownloadCard
          filename={filename}
          size={selectedRow?.size ?? null}
          onDownload={handleDownload}
          downloading={downloading}
        />
      );
    }
    const text = isCurrent
      ? asPreviewString(artifact.spec) || (selectedRow?.preview_text ?? '')
      : (selectedRow?.preview_text ?? '');
    return (
      <pre className="h-full overflow-auto p-4 text-xs whitespace-pre-wrap text-gray-700 dark:text-gray-300">
        {text || 'No preview for this version.'}
      </pre>
    );
  };

  return (
    <div className="flex h-full w-full flex-col gap-3 overflow-hidden">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={String(selectedVersion)}
          onValueChange={(v) => setSelectedVersion(Number(v))}
        >
          <SelectTrigger className="h-8 w-auto gap-2 rounded-md px-3 text-xs">
            <History className="h-3.5 w-3.5" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {versionsDesc.map((v) => (
              <SelectItem key={v.version} value={String(v.version)}>
                Version {v.version}
                {v.version === artifact.current_version ? ' (current)' : ''}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleDownload}
          disabled={downloading}
        >
          {downloading ? (
            <Spinner size="small" />
          ) : (
            <Download className="h-4 w-4" />
          )}
          Download
        </Button>

        {!isCurrent && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleRestore}
            disabled={restoring}
          >
            {restoring ? (
              <Spinner size="small" />
            ) : (
              <RotateCcw className="h-4 w-4" />
            )}
            Restore
          </Button>
        )}
      </div>

      {actionError && <p className="text-xs text-red-500">{actionError}</p>}

      <div className="min-h-0 flex-1 overflow-hidden">{renderPreview()}</div>
    </div>
  );
}
