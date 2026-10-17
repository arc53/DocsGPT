import type { ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import ConfirmationModal from '../../modals/ConfirmationModal';
import type { ActiveState } from '../../models/misc';
import SourceMarkdown from '../SourceMarkdown';
import { Button } from '../ui/button';
import { EmptyState } from '../ui/empty-state';
import {
  PanelBody,
  PanelFooter,
  PanelHeader,
  SidePanel,
} from '../ui/side-panel';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs';
import { Textarea } from '../ui/textarea';

export interface SourceEditSheetProps {
  open: boolean;
  /** Called once the drawer may close (after the discard check). */
  onClose: () => void;
  title: string;
  description?: ReactNode;
  /** The draft, controlled by the caller. */
  value: string;
  onChange: (value: string) => void;
  /** Whether the draft differs from what's saved; enables Save and the discard check. */
  dirty: boolean;
  onSave: () => void;
  saving?: boolean;
  /** Submit label ("Save", "Add chunk"). */
  saveLabel: string;
  /** A save result the user must read (conflict, failure), above the field. */
  alert?: ReactNode;
  /**
   * Fields edited with the content (a chunk's title), under the header and
   * above the Write / Preview tabs. Their changes count toward `dirty`.
   */
  fields?: ReactNode;
  /** Accessible name of the editor. */
  fieldLabel: string;
  placeholder?: string;
}

/**
 * The drawer a source view edits in (a wiki page, a chunk): the rendered
 * content stays on the page behind the scrim while the raw markdown is
 * edited here, with a Preview tab that renders the draft the same way. Built
 * like WorkflowDetailsSheet: header, one filling body, then Cancel and Save.
 * Closing with unsaved edits asks first.
 */
export default function SourceEditSheet({
  open,
  onClose,
  title,
  description,
  value,
  onChange,
  dirty,
  onSave,
  saving = false,
  saveLabel,
  alert,
  fields,
  fieldLabel,
  placeholder,
}: SourceEditSheetProps) {
  const { t } = useTranslation();
  const [tab, setTab] = useState('write');
  const [discardState, setDiscardState] = useState<ActiveState>('INACTIVE');

  // Every open starts on Write, however the last one closed (the caller
  // closes the sheet itself after a save).
  useEffect(() => {
    if (open) setTab('write');
  }, [open]);

  const requestClose = () => {
    if (saving) return;
    if (dirty) setDiscardState('ACTIVE');
    else close();
  };

  const close = () => {
    setTab('write');
    onClose();
  };

  return (
    <>
      <SidePanel
        open={open}
        onOpenChange={(next) => !next && requestClose()}
        size="wide"
        {...(description ? {} : { 'aria-describedby': undefined })}
      >
        <PanelHeader
          title={title}
          description={
            description ? (
              <span className="font-mono text-xs wrap-anywhere">
                {description}
              </span>
            ) : undefined
          }
        />
        {fields ? (
          <div className="flex flex-col gap-5 px-6 pt-2 pb-5">{fields}</div>
        ) : null}
        <Tabs
          value={tab}
          onValueChange={setTab}
          className="flex min-h-0 flex-1 flex-col"
        >
          <TabsList className="mx-6">
            <TabsTrigger value="write">
              {t('settings.sources.editor.write')}
            </TabsTrigger>
            <TabsTrigger value="preview">
              {t('settings.sources.editor.preview')}
            </TabsTrigger>
          </TabsList>
          {/* The one scroller, under the fixed tab row. */}
          <PanelBody>
            {alert}
            <TabsContent value="write" className="flex min-h-0 flex-1">
              <Textarea
                value={value}
                onChange={(event) => onChange(event.target.value)}
                aria-label={fieldLabel}
                placeholder={placeholder}
                resize="none"
                className="min-h-[50svh] flex-1 font-mono"
                disabled={saving}
              />
            </TabsContent>
            <TabsContent value="preview">
              {value.trim() ? (
                <SourceMarkdown content={value} />
              ) : (
                <EmptyState
                  size="xs"
                  illustration="none"
                  title={t('settings.sources.editor.previewEmpty')}
                />
              )}
            </TabsContent>
          </PanelBody>
        </Tabs>
        <PanelFooter>
          <Button
            type="button"
            variant="ghost"
            size="lg"
            shape="pill"
            onClick={requestClose}
            disabled={saving}
          >
            {t('settings.sources.editor.cancel')}
          </Button>
          <Button
            type="button"
            size="lg"
            shape="pill"
            disabled={!dirty || !value.trim()}
            loading={saving}
            onClick={onSave}
          >
            {saveLabel}
          </Button>
        </PanelFooter>
      </SidePanel>
      <ConfirmationModal
        message={t('settings.sources.editor.discardMessage')}
        modalState={discardState}
        setModalState={setDiscardState}
        submitLabel={t('settings.sources.editor.discard')}
        handleSubmit={close}
        variant="destructive"
      />
    </>
  );
}
