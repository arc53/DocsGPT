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
import { Separator } from '../ui/separator';
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '../ui/sheet';
import type { GraphNodeChunk } from '../graphViewUtils';
import { chunkFileName, chunkFilePath, chunkHeading } from './graphCanvasUtils';

interface GraphChunkSheetProps {
  docId: string;
  /** The chunk to show; null closes both drawers. */
  chunk: GraphNodeChunk | null;
  /** The entity's name, marked in the rendered chunk. */
  highlight: string;
  /** Called once the drawers close (the node stays selected). */
  onClose: () => void;
  /** Show the chunk's file on the Files tab; omitted hides the button. */
  onOpenInFiles?: (path: string) => void;
  /** Called after a saved edit, to refetch the node detail. */
  onSaved?: () => void;
}

/**
 * A source chunk of a graph entity, opened from the node panel: a read drawer
 * with the chunk rendered (the entity's name marked), "Open in Files" and
 * Edit; Edit swaps it for the shared edit drawer. Built like
 * WorkflowDetailsSheet: header, one scrolling body, then the actions.
 */
export default function GraphChunkSheet({
  docId,
  chunk,
  highlight,
  onClose,
  onOpenInFiles,
  onSaved,
}: GraphChunkSheetProps) {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [draftTitle, setDraftTitle] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);

  // Every newly opened chunk starts in the read drawer.
  useEffect(() => {
    setEditing(false);
    setSaveFailed(false);
  }, [chunk?.chunk_id]);

  if (!chunk) return null;

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

  const close = () => {
    setEditing(false);
    setSaveFailed(false);
    onClose();
  };

  // Leaving the edit drawer without saving returns to the read drawer.
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
      <Sheet open={!editing} onOpenChange={(open) => !open && close()}>
        <SheetContent
          side="right"
          size="detail"
          className="p-0"
          closeLabel={t('settings.sources.editor.close')}
        >
          <div className="flex min-h-0 flex-1 flex-col">
            {/* pr-12 keeps the header clear of the close X at top-2 right-2. */}
            <div className="flex flex-col gap-1 px-6 pt-6 pr-12 pb-4">
              <SheetTitle className="wrap-break-word">{title}</SheetTitle>
              {readMeta ? (
                <SheetDescription className="wrap-anywhere">
                  {readMeta}
                </SheetDescription>
              ) : null}
            </div>
            <Separator />
            <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
              <SourceMarkdown
                content={chunk.text ?? ''}
                highlight={highlight}
              />
            </div>
            <Separator />
            <div className="flex justify-end gap-3 px-6 py-4">
              {onOpenInFiles && path ? (
                <Button
                  type="button"
                  variant="outline"
                  size="lg"
                  shape="pill"
                  onClick={() => {
                    close();
                    onOpenInFiles(path);
                  }}
                >
                  {t('settings.sources.graphrag.view.openInFiles')}
                </Button>
              ) : null}
              <Button type="button" size="lg" shape="pill" onClick={startEdit}>
                <Pencil />
                {t('modals.chunk.edit')}
              </Button>
            </div>
          </div>
        </SheetContent>
      </Sheet>
      <SourceEditSheet
        open={editing}
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
