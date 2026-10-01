import { Pencil } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../../api/services/userService';
import { showActionToast } from '../../notifications/actionToastSlice';
import { selectToken } from '../../preferences/preferenceSlice';
import { UNKNOWN_TOKEN_COUNT, formatChunkTokens } from '../chunkUtils';
import SourceMarkdown from '../SourceMarkdown';
import SourceEditSheet from '../tree/SourceEditSheet';
import { Alert, AlertDescription } from '../ui/alert';
import { Button } from '../ui/button';
import { FormField } from '../ui/form-field';
import { Input } from '../ui/input';
import { PanelBody, PanelFooter, PanelHeader } from '../ui/side-panel';
import type { GraphNodeChunk } from '../graphViewUtils';
import { chunkFileName, chunkFilePath, chunkHeading } from './graphCanvasUtils';

interface GraphChunkReaderProps {
  docId: string;
  chunk: GraphNodeChunk;
  /** The entity's name, marked in the rendered chunk. */
  highlight: string;
  /** Back to the entity (the header's arrow, Open in Files, a saved edit). */
  onBack: () => void;
  /** Show the chunk's file on the Files tab; omitted hides the button. */
  onOpenInFiles?: (path: string) => void;
  /** Called after a saved edit, to refetch the node detail. */
  onSaved?: () => void;
  /** Whether the reader offers Edit (`can(source, 'edit')`). */
  canEdit?: boolean;
}

/**
 * A source chunk of a graph entity, the second level of the node's side
 * panel: a Back arrow, the chunk rendered (the entity's name marked), then
 * "Open in Files" and Edit. Edit opens the shared modal edit drawer over it.
 * Render it inside the node's SidePanel, keyed on the chunk.
 */
export default function GraphChunkReader({
  docId,
  chunk,
  highlight,
  onBack,
  onOpenInFiles,
  onSaved,
  canEdit = true,
}: GraphChunkReaderProps) {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [draftTitle, setDraftTitle] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);

  // Every newly opened chunk starts in the reader.
  useEffect(() => {
    setEditing(false);
    setSaveFailed(false);
  }, [chunk.chunk_id]);

  const file = chunkFileName(chunk.metadata);
  // The tree path "Open in Files" opens (a web page's is not its URL).
  const path = chunkFilePath(chunk.metadata);
  const tokens = formatChunkTokens(
    (chunk.metadata ?? {}) as Parameters<typeof formatChunkTokens>[0],
  );
  const hasTokens = tokens !== UNKNOWN_TOKEN_COUNT;
  const heading = chunkHeading(chunk.text);
  const title = heading || file || t('settings.sources.graphrag.view.chunk');
  const meta =
    file && hasTokens
      ? t('settings.sources.graphrag.view.chunkMeta', {
          file,
          tokens,
          interpolation: { escapeValue: false },
        })
      : hasTokens
        ? t('settings.sources.graphrag.view.chunkTokens', { tokens })
        : file;
  // When the file name is already the title, the read header shows only the
  // token count; the edit drawer keeps the full line.
  const readMeta =
    heading || !file
      ? meta
      : hasTokens
        ? t('settings.sources.graphrag.view.chunkTokens', { tokens })
        : '';

  const showOpenInFiles = !!onOpenInFiles && !!path;

  const close = () => {
    setEditing(false);
    setSaveFailed(false);
    onBack();
  };

  // Leaving the edit drawer without saving returns to the reader.
  const leaveEdit = () => {
    setEditing(false);
    setSaveFailed(false);
  };

  const savedTitle =
    typeof chunk.metadata?.title === 'string' ? chunk.metadata.title : '';

  const startEdit = () => {
    setDraft(chunk.text ?? '');
    setDraftTitle(savedTitle);
    setSaveFailed(false);
    setEditing(true);
  };

  const save = async () => {
    setSaving(true);
    setSaveFailed(false);
    // The backend merges metadata: send a title only when the chunk had one
    // (clearing it sends '') or one was entered, never '' onto an untitled
    // one. As Chunks does.
    const sendTitle = !!savedTitle || !!draftTitle.trim();
    try {
      const response = await userService.updateChunk(
        {
          id: docId,
          chunk_id: chunk.chunk_id,
          text: draft,
          ...(sendTitle ? { metadata: { title: draftTitle.trim() } } : {}),
        },
        token,
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      close();
      onSaved?.();
      dispatch(
        showActionToast({
          variant: 'success',
          message: t('settings.sources.graphrag.view.chunkSaved'),
        }),
      );
    } catch (error) {
      console.error('Error saving chunk:', error);
      setSaveFailed(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <PanelHeader
        title={title}
        description={
          readMeta ? (
            <span className="wrap-anywhere">{readMeta}</span>
          ) : undefined
        }
        onBack={onBack}
      />
      <PanelBody>
        <SourceMarkdown content={chunk.text ?? ''} highlight={highlight} />
      </PanelBody>
      {/* A reader with nothing to open or edit gets no action row. */}
      {showOpenInFiles || canEdit ? (
        <PanelFooter>
          {showOpenInFiles ? (
            <Button
              type="button"
              variant="outline"
              size="lg"
              shape="pill"
              onClick={() => {
                close();
                onOpenInFiles?.(path);
              }}
            >
              {t('settings.sources.graphrag.view.openInFiles')}
            </Button>
          ) : null}
          {canEdit ? (
            <Button type="button" size="lg" shape="pill" onClick={startEdit}>
              <Pencil />
              {t('modals.chunk.edit')}
            </Button>
          ) : null}
        </PanelFooter>
      ) : null}
      <SourceEditSheet
        open={canEdit && editing}
        onClose={leaveEdit}
        title={t('settings.sources.graphrag.view.editChunk')}
        description={meta || undefined}
        value={draft}
        onChange={setDraft}
        dirty={draft !== (chunk.text ?? '') || draftTitle.trim() !== savedTitle}
        fields={
          <FormField
            label={t('modals.chunk.title')}
            hint={t('settings.sources.chunkTitleHint')}
            labelSurface="background"
          >
            <Input
              value={draftTitle}
              onChange={(event) => setDraftTitle(event.target.value)}
              disabled={saving}
            />
          </FormField>
        }
        onSave={save}
        saving={saving}
        saveLabel={t('modals.chunk.save')}
        alert={
          saveFailed ? (
            <Alert variant="destructive">
              <AlertDescription>
                {t('settings.sources.chunkErrors.save')}
              </AlertDescription>
            </Alert>
          ) : null
        }
        fieldLabel={t('modals.chunk.bodyText')}
      />
    </>
  );
}
