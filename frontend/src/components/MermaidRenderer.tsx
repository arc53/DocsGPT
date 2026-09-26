import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { CircleAlert } from 'lucide-react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import {
  oneLight,
  vscDarkPlus,
} from 'react-syntax-highlighter/dist/cjs/styles/prism';

import { selectStatus } from '../conversation/conversationSlice';
import { useDarkTheme } from '../hooks';
import CopyButton from './CopyButton';
import { renderMermaidDiagram } from './mermaidSecurity';
import { Alert, AlertDescription } from './ui/alert';
import { Button } from './ui/button';
import { IconButton } from './ui/icon-button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from './ui/dropdown-menu';
import { MermaidRendererProps } from './types';

const MermaidRenderer: React.FC<MermaidRendererProps> = ({
  code,
  isLoading,
}) => {
  const { t } = useTranslation();
  const [isDarkTheme] = useDarkTheme();
  const diagramId = useRef(
    `mermaid-${Date.now()}-${Math.random().toString(36).substring(2)}`,
  );
  const renderSequence = useRef(0);
  const status = useSelector(selectStatus);
  const [error, setError] = useState<string | null>(null);
  const [showCode, setShowCode] = useState<boolean>(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const diagramRef = useRef<HTMLPreElement>(null);
  const [hoverPosition, setHoverPosition] = useState<{
    x: number;
    y: number;
  } | null>(null);
  const [isHovering, setIsHovering] = useState<boolean>(false);
  const [zoomFactor, setZoomFactor] = useState<number>(2);

  const handleMouseMove = (event: React.MouseEvent) => {
    if (!containerRef.current) return;

    const rect = containerRef.current.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width;
    const y = (event.clientY - rect.top) / rect.height;

    setHoverPosition({ x, y });
  };

  const handleMouseEnter = () => setIsHovering(true);
  const handleMouseLeave = () => {
    setIsHovering(false);
    setHoverPosition(null);
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (!isHovering) return;

    if (event.key === '+' || event.key === '=') {
      setZoomFactor((prev) => Math.min(6, prev + 0.5)); // Cap at 6x
      event.preventDefault();
    } else if (event.key === '-') {
      setZoomFactor((prev) => Math.max(1, prev - 0.5)); // Minimum 1x
      event.preventDefault();
    }
  };

  const handleWheel = (event: React.WheelEvent) => {
    if (!isHovering) return;

    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();

      if (event.deltaY < 0) {
        setZoomFactor((prev) => Math.min(6, prev + 0.25));
      } else {
        setZoomFactor((prev) => Math.max(1, prev - 0.25));
      }
    }
  };

  const getTransformOrigin = () => {
    if (!hoverPosition) return 'center center';
    return `${hoverPosition.x * 100}% ${hoverPosition.y * 100}%`;
  };

  const isCurrentlyLoading =
    isLoading !== undefined ? isLoading : status === 'loading';

  useEffect(() => {
    let cancelled = false;
    const renderDiagram = async () => {
      if (!isCurrentlyLoading && code) {
        try {
          setError(null);
          const { svg, bindFunctions } = await renderMermaidDiagram({
            // Mermaid owns and removes this temporary ID while rendering. It
            // must never match the visible host's ID.
            id: `${diagramId.current}-render-${++renderSequence.current}`,
            code,
            isDarkTheme,
            securityLevel: 'strict',
          });
          if (cancelled) return;

          const element = diagramRef.current;
          if (element) {
            // Mermaid strict mode sanitizes this generated SVG before it is returned.
            element.innerHTML = svg;
            bindFunctions?.(element);
          }
        } catch (err) {
          if (cancelled) return;
          console.error('Error rendering mermaid diagram:', err);
          setError(
            t('mermaid.renderFailed', {
              message: err instanceof Error ? err.message : String(err),
            }),
          );
        }
      }
    };

    renderDiagram();
    return () => {
      cancelled = true;
    };
  }, [code, isDarkTheme, isCurrentlyLoading]);

  const downloadSvg = (): void => {
    const element = document.getElementById(diagramId.current);
    if (!element) return;
    const svgElement = element.querySelector('svg');
    if (!svgElement) return;

    const svgClone = svgElement.cloneNode(true) as SVGElement;

    if (!svgClone.hasAttribute('xmlns')) {
      svgClone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    }

    if (!svgClone.hasAttribute('width') || !svgClone.hasAttribute('height')) {
      const viewBox = svgClone.getAttribute('viewBox')?.split(' ') || [];
      if (viewBox.length === 4) {
        svgClone.setAttribute('width', viewBox[2]);
        svgClone.setAttribute('height', viewBox[3]);
      }
    }

    const serializer = new XMLSerializer();
    const svgString = serializer.serializeToString(svgClone);

    const svgBlob = new Blob(
      [`<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n${svgString}`],
      { type: 'image/svg+xml' },
    );

    const url = URL.createObjectURL(svgBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'diagram.svg';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const downloadPng = (): void => {
    const element = document.getElementById(diagramId.current);
    if (!element) return;

    const svgElement = element.querySelector('svg');
    if (!svgElement) return;

    const svgClone = svgElement.cloneNode(true) as SVGElement;

    if (!svgClone.hasAttribute('xmlns')) {
      svgClone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    }

    let width = parseInt(svgClone.getAttribute('width') || '0');
    let height = parseInt(svgClone.getAttribute('height') || '0');

    if (!width || !height) {
      const viewBox = svgClone.getAttribute('viewBox')?.split(' ') || [];
      if (viewBox.length === 4) {
        width = parseInt(viewBox[2]);
        height = parseInt(viewBox[3]);
        svgClone.setAttribute('width', width.toString());
        svgClone.setAttribute('height', height.toString());
      } else {
        width = 800;
        height = 600;
        svgClone.setAttribute('width', width.toString());
        svgClone.setAttribute('height', height.toString());
      }
    }

    const serializer = new XMLSerializer();
    const svgString = serializer.serializeToString(svgClone);
    const svgBase64 = btoa(unescape(encodeURIComponent(svgString)));
    const dataUrl = `data:image/svg+xml;base64,${svgBase64}`;

    const img = new Image();
    img.crossOrigin = 'anonymous';

    img.onload = function (): void {
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;

      const ctx = canvas.getContext('2d');
      if (!ctx) {
        console.error('Could not get canvas context');
        return;
      }

      ctx.fillRect(0, 0, canvas.width, canvas.height);

      ctx.drawImage(img, 0, 0, width, height);

      try {
        const pngUrl = canvas.toDataURL('image/png');
        const link = document.createElement('a');
        link.download = 'diagram.png';
        link.href = pngUrl;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      } catch (e) {
        console.error('Failed to create PNG:', e);
        // Fallback to SVG download if PNG fails
        downloadSvg();
      }
    };

    img.src = dataUrl;
  };

  const downloadMmd = (): void => {
    const blob = new Blob([code], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'diagram.mmd';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const downloadOptions = [
    { label: t('mermaid.downloadAs', { format: 'SVG' }), action: downloadSvg },
    { label: t('mermaid.downloadAs', { format: 'PNG' }), action: downloadPng },
    { label: t('mermaid.downloadAs', { format: 'MMD' }), action: downloadMmd },
  ];

  const showDiagramOptions = !isCurrentlyLoading && !error;
  const errorRender = !isCurrentlyLoading && error;

  return (
    <div className="group border-border bg-card relative overflow-hidden rounded-xl border">
      <div className="bg-muted flex items-center justify-between px-2 py-1">
        <span className="text-foreground text-xs font-medium">mermaid</span>
        <div className="flex items-center gap-2">
          <CopyButton
            textToCopy={String(code).replace(/\n$/, '')}
            side="bottom"
          />

          {showDiagramOptions && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button type="button" variant="ghost-muted" size="xs">
                  {t('mermaid.download')} <span className="ml-1">▼</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-40">
                {downloadOptions.map((option) => (
                  <DropdownMenuItem
                    key={option.label}
                    onSelect={() => option.action()}
                  >
                    {option.label}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}

          {showDiagramOptions && (
            <Button
              type="button"
              variant={showCode ? 'secondary' : 'ghost-muted'}
              size="xs"
              onClick={() => setShowCode(!showCode)}
            >
              {t('mermaid.code')}
            </Button>
          )}
        </div>
      </div>

      {isCurrentlyLoading ? (
        <div className="bg-card flex items-center justify-center p-4">
          <div className="text-muted-foreground text-sm">
            {t('mermaid.loading')}
          </div>
        </div>
      ) : errorRender ? (
        <Alert variant="destructive" className="m-2 w-auto">
          <CircleAlert />
          <AlertDescription className="overflow-auto wrap-break-word whitespace-normal">
            {error}
          </AlertDescription>
        </Alert>
      ) : (
        <>
          <div
            ref={containerRef}
            className="no-scrollbar bg-card relative block w-full p-4"
            style={{
              overflow: 'auto',
              scrollbarWidth: 'none',
              msOverflowStyle: 'none',
              width: '100%',
            }}
            onMouseMove={handleMouseMove}
            onMouseEnter={handleMouseEnter}
            onMouseLeave={handleMouseLeave}
            onKeyDown={handleKeyDown}
            onWheel={handleWheel}
            tabIndex={0}
          >
            {isHovering && (
              <>
                <div className="absolute top-2 right-2 z-10 flex items-center gap-2 rounded-sm bg-black/70 px-2 py-1 text-xs text-white">
                  <IconButton
                    label={t('mermaid.decreaseZoom')}
                    side="bottom"
                    variant="ghost"
                    size="icon-xs"
                    onClick={() =>
                      setZoomFactor((prev) => Math.max(1, prev - 0.5))
                    }
                    /* eslint-disable-next-line shadcn/no-restyle --
                       zoom controls sit on the bg-black/70 overlay; ghost's accent hover would paint a light square on it */
                    className="hover:bg-white/20 hover:text-white"
                  >
                    -
                  </IconButton>
                  <Button
                    type="button"
                    variant="link"
                    size="inline"
                    onClick={() => setZoomFactor(2)}
                    title={t('mermaid.resetZoom')}
                    /* eslint-disable-next-line shadcn/no-restyle --
                       on the bg-black/70 zoom overlay, like its − / + siblings: keeps the overlay's white 12px regular */
                    className="text-xs font-normal text-current"
                  >
                    {zoomFactor.toFixed(1)}x
                  </Button>
                  <IconButton
                    label={t('mermaid.increaseZoom')}
                    side="bottom"
                    variant="ghost"
                    size="icon-xs"
                    onClick={() =>
                      setZoomFactor((prev) => Math.min(6, prev + 0.5))
                    }
                    /* eslint-disable-next-line shadcn/no-restyle --
                       zoom controls sit on the bg-black/70 overlay; ghost's accent hover would paint a light square on it */
                    className="hover:bg-white/20 hover:text-white"
                  >
                    +
                  </IconButton>
                </div>
              </>
            )}
            <pre
              ref={diagramRef}
              className="w-full select-none"
              id={diagramId.current}
              key={`mermaid-${diagramId.current}`}
              style={{
                transform: isHovering ? `scale(${zoomFactor})` : `scale(1)`,
                transformOrigin: getTransformOrigin(),
                transition: 'transform 0.2s ease',
                cursor: 'default',
                width: '100%',
                display: 'flex',
                justifyContent: 'center',
              }}
            />
          </div>

          {showCode && (
            <div className="border-border border-t">
              <div className="bg-muted p-2">
                <span className="text-foreground text-xs font-medium">
                  {t('mermaid.codeTitle')}
                </span>
              </div>
              <SyntaxHighlighter
                language="mermaid"
                style={isDarkTheme ? vscDarkPlus : oneLight}
                customStyle={{
                  margin: 0,
                  borderRadius: 0,
                  scrollbarWidth: 'thin',
                  maxHeight: '300px',
                }}
              >
                {code}
              </SyntaxHighlighter>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default MermaidRenderer;
