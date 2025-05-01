import React, { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';
import CopyButton from './CopyButton';
import { useSelector } from 'react-redux';
import { selectStatus } from '../conversation/conversationSlice';
import { MermaidRendererProps } from './types';

const MermaidRenderer: React.FC<MermaidRendererProps> = ({
  code,
  isDarkTheme,
}) => {
  const diagramId = useRef(`mermaid-${crypto.randomUUID()}`);
  const status = useSelector(selectStatus);
  const [svgContent, setSvgContent] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [showCode, setShowCode] = useState<boolean>(false);
  const [showDownloadMenu, setShowDownloadMenu] = useState<boolean>(false);
  const downloadMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (status === 'loading' || !code) return;

    mermaid.initialize({
      startOnLoad: true,
      theme: isDarkTheme ? 'dark' : 'default',
      securityLevel: 'loose',
      suppressErrorRendering: true
    });

    const renderDiagram = async (): Promise<void> => {
      try {
        const element = document.getElementById(diagramId.current);
        if (element) {
          element.removeAttribute('data-processed');
          element.innerHTML = code;
          mermaid.contentLoaded();
          
          const svgElement = element.querySelector('svg');
          if (svgElement) {
            setSvgContent(svgElement.outerHTML);
          }
          setError(null);
        }
      } catch (err) {
        setError(
          `Failed to render Mermaid diagram: ${err instanceof Error ? err.message : String(err)}`
        );
        setSvgContent('');
      }
    };

    renderDiagram();
  }, [code, isDarkTheme, status]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        downloadMenuRef.current &&
        !downloadMenuRef.current.contains(event.target as Node)
      ) {
        setShowDownloadMenu(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showDownloadMenu]);

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
      { type: 'image/svg+xml' }
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
    
    img.onload = function(): void {
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
    { label: 'Download as SVG', action: downloadSvg },
    { label: 'Download as PNG', action: downloadPng },
    { label: 'Download as MMD', action: downloadMmd },
  ];

  const showDiagramOptions = status !== 'loading' && !error;
  const errorRender = status !== 'loading' && error;

  return (
    <div className="group relative rounded-lg overflow-hidden border border-light-silver dark:border-raisin-black">
      <div className="flex justify-between items-center px-2 py-1 bg-platinum dark:bg-eerie-black-2">
        <span className="text-xs font-medium text-just-black dark:text-chinese-white">
          mermaid
        </span>
        <div className="flex items-center gap-2">
          <CopyButton text={String(code).replace(/\n$/, '')} />
  
          {showDiagramOptions && (
            <div className="relative" ref={downloadMenuRef}>
              <button
                onClick={() => setShowDownloadMenu(!showDownloadMenu)}
                className="text-xs px-2 py-1 bg-gray-100 dark:bg-gray-700 rounded flex items-center h-full"
                title="Download options"
              >
                Download <span className="ml-1">▼</span>
              </button>
              {showDownloadMenu && (
                <div className="absolute right-0 mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded shadow-lg z-10 w-40">
                  <ul>
                    {downloadOptions.map((option, index) => (
                      <li key={index}>
                        <button
                          onClick={() => {
                            option.action();
                            setShowDownloadMenu(false);
                          }}
                          className="text-xs px-4 py-2 w-full text-left hover:bg-gray-100 dark:hover:bg-gray-700"
                        >
                          {option.label}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
  
          {showDiagramOptions && (
            <button
              onClick={() => setShowCode(!showCode)}
              className={`text-xs px-2 py-1 rounded flex items-center h-full ${
                showCode
                  ? 'bg-blue-200 dark:bg-blue-800'
                  : 'bg-gray-100 dark:bg-gray-700'
              }`}
              title="View Code"
            >
              Code
            </button>
          )}
        </div>
      </div>
  
      {status === 'loading' ? (
        <div className="p-4 bg-white dark:bg-eerie-black flex justify-center items-center">
          <div className="text-sm text-gray-500 dark:text-gray-400">
            Loading diagram...
          </div>
        </div>
      ) : errorRender ? (
        <div className="border-2 border-red-400 dark:border-red-700 rounded m-2">
          <div className="bg-red-100 dark:bg-red-900/30 px-4 py-2 text-red-800 dark:text-red-300 text-sm whitespace-normal break-words overflow-auto">
            {error}
          </div>
        </div>
      ) : (
        <div className="flex flex-col md:flex-row">
          <div className={`p-4 bg-white dark:bg-eerie-black flex justify-center items-center ${
            showCode ? 'md:w-1/2' : 'w-full'
          }`}>
            <div className="mermaid" id={diagramId.current}>
              {code}
            </div>
          </div>
  
          {showCode && (
            <pre className="p-4 whitespace-pre-wrap overflow-auto bg-white dark:bg-eerie-black text-just-black dark:text-chinese-white border-t md:border-t-0 md:border-l border-light-silver dark:border-raisin-black md:w-1/2">
              {code}
            </pre>
          )}
        </div>
      )}
    </div>
  );
};

export default MermaidRenderer;
