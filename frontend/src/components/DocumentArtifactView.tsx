import {
  CircleAlert,
  Download,
  FileText,
  History,
  RotateCcw,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { useDarkTheme } from '../hooks';
import { selectToken } from '../preferences/preferenceSlice';
import MarkdownPreview from './MarkdownPreview';
import { renderMermaidDiagram } from './mermaidSecurity';
import { LoadingState } from '@/components/ui/loading-state';
import {
  buildPreviewDocument,
  bytesPreviewModeForMime,
  displayFilename,
  findCurrentVersion,
  formatBytes,
  previewModeForKind,
  sortVersionsDesc,
  triggerResponseDownload,
  type ArtifactVersion,
  type BytesPreviewMode,
  type DocumentArtifact,
} from './artifactViewUtils';
import { Alert, AlertDescription } from './ui/alert';
import { Button } from './ui/button';
import { useArtifactBytes } from './useArtifactBytes';
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
  const { t } = useTranslation();
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
    renderMermaidDiagram({
      id: `artifact-mermaid-${Date.now()}`,
      code: source,
      isDarkTheme,
      securityLevel: 'sandbox',
    })
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
      <pre className="text-muted-foreground overflow-auto p-4 font-mono text-xs wrap-break-word whitespace-pre-wrap">
        {source}
      </pre>
    );
  }
  if (rendered === null) {
    return <LoadingState fill="parent" />;
  }

  // For mermaid, `rendered` is mermaid's sandboxed-iframe wrapper; the 'mermaid'
  // preview document carries a CSP that permits its inner `data:` frame.
  const previewKind = isMermaid ? 'mermaid' : artifactKind;
  return (
    <iframe
      // No allow-same-origin: content is fully isolated from the app origin.
      sandbox=""
      title={t('components.artifact.preview')}
      className="border-border h-full w-full rounded-md border bg-white"
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
  const { t } = useTranslation();
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4">
      <div className="border-border flex flex-col items-center gap-3 rounded-xl border p-8 text-center">
        <FileText className="text-muted-foreground size-12" />
        <div>
          <p className="text-foreground text-sm font-medium break-all">
            {filename}
          </p>
          {size != null && (
            <p className="text-muted-foreground text-xs">{formatBytes(size)}</p>
          )}
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onDownload}
          loading={downloading}
        >
          <Download />
          {t('components.artifact.download')}
        </Button>
      </div>
    </div>
  );
}

/**
 * Render a version's downloadable BYTES inline by fetching them through the
 * authed download path. html/svg are embedded ONLY inside the scriptless
 * `sandbox=""` + CSP iframe (never the app DOM); images are shown via an inert
 * blob-URL `<img>`; text/markdown render as escaped React content. On fetch
 * error (or oversized text) it falls back to the supplied download card.
 */
function BytesPreview({
  artifactId,
  version,
  mode,
  token,
  fallback,
}: {
  artifactId: string;
  version: number;
  mode: Exclude<BytesPreviewMode, 'card'>;
  token: string | null;
  fallback: ReactNode;
}) {
  const { t } = useTranslation();
  const state = useArtifactBytes(artifactId, version, mode, token);

  if (state.status === 'loading') {
    return <LoadingState fill="parent" />;
  }
  if (state.status === 'error') {
    return <>{fallback}</>;
  }
  if (state.status === 'image') {
    return (
      <div className="flex h-full items-center justify-center overflow-auto p-4">
        <img
          src={state.url}
          alt={t('components.artifact.preview')}
          className="max-h-full max-w-full object-contain"
        />
      </div>
    );
  }
  // state.status === 'text'
  if (mode === 'iframe-html' || mode === 'iframe-svg') {
    return (
      <iframe
        // No allow-same-origin / no scripts: bytes are isolated from the app origin.
        sandbox=""
        title={t('components.artifact.preview')}
        className="border-border h-full w-full rounded-md border bg-white"
        srcDoc={buildPreviewDocument(
          mode === 'iframe-svg' ? 'svg' : 'html',
          state.text,
        )}
      />
    );
  }
  if (mode === 'text-markdown') {
    return <MarkdownPreview content={state.text} />;
  }
  return (
    <pre className="text-foreground h-full overflow-auto p-4 font-mono text-xs wrap-break-word whitespace-pre-wrap">
      {state.text}
    </pre>
  );
}

export default function DocumentArtifactView({
  artifact,
  onRefresh,
}: {
  artifact: DocumentArtifact;
  onRefresh: () => void;
}) {
  const { t } = useTranslation();
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
        'url',
      );
      const ok = await triggerResponseDownload(response, filename);
      if (!ok && isMountedRef.current)
        setActionError(t('components.artifact.downloadFailed'));
    } catch {
      if (isMountedRef.current)
        setActionError(t('components.artifact.downloadFailed'));
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
        if (isMountedRef.current)
          setActionError(t('components.artifact.restoreFailed'));
        return;
      }
      if (isMountedRef.current) onRefresh();
    } catch {
      if (isMountedRef.current)
        setActionError(t('components.artifact.restoreFailed'));
    } finally {
      if (isMountedRef.current) setRestoring(false);
    }
  };

  const downloadCard = (
    <DownloadCard
      filename={filename}
      size={selectedRow?.size ?? null}
      onDownload={handleDownload}
      downloading={downloading}
    />
  );

  const renderPreview = () => {
    // Preferred path: the version's `spec` already carries renderable
    // html/svg/mermaid markup — render it in the sandboxed frame, no fetch.
    if (mode === 'frame') {
      const source = asPreviewString(
        isCurrent ? artifact.spec : selectedRow?.preview_text,
      );
      if (source) {
        return <FramePreview artifactKind={artifact.kind} source={source} />;
      }
      // No usable spec content: fall through to the bytes path below.
    }

    // Inline text already on hand (code/data kinds expose it as preview_text /
    // spec) — render it without a fetch.
    if (mode === 'text') {
      const text = isCurrent
        ? asPreviewString(artifact.spec) || (selectedRow?.preview_text ?? '')
        : (selectedRow?.preview_text ?? '');
      if (text) {
        return (
          <pre className="text-foreground h-full overflow-auto p-4 font-mono text-xs wrap-break-word whitespace-pre-wrap">
            {text}
          </pre>
        );
      }
      // No inline text: try fetching the bytes below.
    }

    // Bytes path: no usable spec/inline content, so decide the preview by the
    // version's mime (kind fallback) and fetch the stored bytes for an inline
    // render. Anything not previewable (office docs, pdf, octet-stream) and any
    // fetch failure fall back to the download card.
    const bytesMode: BytesPreviewMode = bytesPreviewModeForMime(
      selectedRow?.mime_type,
      artifact.kind,
    );
    if (bytesMode === 'card' || !selectedRow) {
      return downloadCard;
    }
    return (
      <BytesPreview
        // Refetch on artifact/version/mode change via the key + hook deps.
        key={`${artifact.id}:${selectedVersion}:${bytesMode}`}
        artifactId={artifact.id}
        version={selectedVersion}
        mode={bytesMode}
        token={token}
        fallback={downloadCard}
      />
    );
  };

  return (
    <div className="flex h-full w-full flex-col gap-3 overflow-hidden">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={String(selectedVersion)}
          onValueChange={(v) => setSelectedVersion(Number(v))}
        >
          <SelectTrigger size="sm" className="w-auto">
            <History className="size-3.5" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {versionsDesc.map((v) => (
              <SelectItem key={v.version} value={String(v.version)}>
                {v.version === artifact.current_version
                  ? t('components.artifact.versionCurrent', {
                      version: v.version,
                    })
                  : t('components.artifact.version', { version: v.version })}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleDownload}
          loading={downloading}
        >
          <Download />
          {t('components.artifact.download')}
        </Button>

        {!isCurrent && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleRestore}
            loading={restoring}
          >
            <RotateCcw />
            {t('components.artifact.restore')}
          </Button>
        )}
      </div>

      {actionError && (
        <Alert variant="destructive">
          <CircleAlert className="size-4" aria-hidden="true" />
          <AlertDescription>{actionError}</AlertDescription>
        </Alert>
      )}

      <div className="min-h-0 flex-1 overflow-hidden">{renderPreview()}</div>
    </div>
  );
}
