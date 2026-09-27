import { CircleX } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { SectionHeader } from '@/components/ui/section-header';
import { Separator } from '@/components/ui/separator';
import { SettingRow } from '@/components/ui/setting-row';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from '@/components/ui/sheet';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';

import { FileUpload } from '../../../components/FileUpload';

export interface WorkflowDetailsValues {
  name: string;
  description: string;
  allowPromptOverride: boolean;
}

export interface WorkflowDetailsSave extends WorkflowDetailsValues {
  /** A newly picked avatar, or null to keep the current one. */
  imageFile: File | null;
}

interface WorkflowDetailsSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The builder's current values; the sheet edits a copy of them. */
  details: WorkflowDetailsValues;
  /** The saved avatar's URL, shown in the tile until a new one is picked. */
  currentImage: string;
  saving: boolean;
  /** Errors from the last save started here, shown at the top of the body. */
  errors: string[];
  onSave: (values: WorkflowDetailsSave) => void;
}

/**
 * The workflow's name, description, avatar and prompt-override setting, in a
 * right drawer laid out like the classic agent's Basics on a phone.
 *
 * The sheet edits a copy: Cancel, the X, Escape and the scrim drop the edits,
 * and Save hands them to the builder, which saves the workflow.
 *
 * Args:
 *   open: Whether the sheet is open.
 *   onOpenChange: Opens or closes the sheet.
 *   details: The values to start from each time it opens.
 *   currentImage: The saved avatar's URL.
 *   saving: Whether a save started here is running.
 *   errors: Errors from that save.
 *   onSave: Receives the edited values.
 */
export default function WorkflowDetailsSheet({
  open,
  onOpenChange,
  details,
  currentImage,
  saving,
  errors,
  onSave,
}: WorkflowDetailsSheetProps) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<WorkflowDetailsValues>(details);
  const [imageFile, setImageFile] = useState<File | null>(null);

  // Start from the builder's values every time the sheet opens.
  useEffect(() => {
    if (!open) return;
    setDraft(details);
    setImageFile(null);
    // Only on open: later changes to `details` come from this sheet's own save.
  }, [open]);

  const dirty =
    imageFile !== null ||
    draft.name !== details.name ||
    draft.description !== details.description ||
    draft.allowPromptOverride !== details.allowPromptOverride;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        size="default"
        className="p-0"
        closeLabel={t('agents.close')}
      >
        <div className="flex min-h-0 flex-1 flex-col">
          {/* pr-12 keeps the header clear of the close X at top-2 right-2. */}
          <div className="flex flex-col gap-1 px-6 pt-6 pr-12 pb-4">
            <SheetTitle>{t('agents.workflow.builder.detailsTitle')}</SheetTitle>
            <SheetDescription>
              {t('agents.workflow.builder.detailsDescription')}
            </SheetDescription>
          </div>
          <Separator />
          <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-6 py-6">
            {errors.length > 0 && (
              <Alert variant="destructive">
                <CircleX />
                <AlertTitle>
                  {t('agents.workflow.builder.unableSave')}
                </AlertTitle>
                <AlertDescription>
                  <ul className="flex list-inside list-disc flex-col gap-1 wrap-break-word">
                    {errors.map((error, index) => (
                      <li key={index}>{error}</li>
                    ))}
                  </ul>
                </AlertDescription>
              </Alert>
            )}
            <Card variant="subtle" padding="lg" className="gap-5">
              <SectionHeader
                as="h3"
                size="xs"
                title={t('agents.form.sections.basics')}
              />
              {/* The phone layout of classic Basics: the avatar beside Name,
                Description across the row. */}
              <div className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-5">
                <FileUpload
                  showPreview
                  size="tile"
                  tileSize="fixed"
                  currentImage={currentImage || undefined}
                  onUpload={(files) => setImageFile(files[0] ?? null)}
                  onRemove={() => setImageFile(null)}
                  uploadText={t('agents.form.labels.avatar')}
                />
                <FormField
                  labelSurface="background"
                  label={t('agents.form.labels.name')}
                >
                  <Input
                    shape="pill"
                    type="text"
                    value={draft.name}
                    placeholder={t(
                      'agents.workflow.builder.workflowNamePlaceholder',
                    )}
                    onChange={(e) =>
                      setDraft({ ...draft, name: e.target.value })
                    }
                  />
                </FormField>
                <FormField
                  labelSurface="background"
                  label={t('agents.form.labels.description')}
                  className="col-span-2"
                >
                  <Textarea
                    size="lg"
                    className="h-32"
                    placeholder={t(
                      'agents.workflow.builder.workflowDescriptionPlaceholder',
                    )}
                    value={draft.description}
                    onChange={(e) =>
                      setDraft({ ...draft, description: e.target.value })
                    }
                  />
                </FormField>
              </div>
            </Card>
            <Card variant="subtle" padding="lg" className="gap-5">
              <SectionHeader
                as="h3"
                size="xs"
                title={t('agents.form.sections.advanced')}
              />
              <SettingRow
                label={t('agents.form.advanced.systemPromptOverride')}
                description={t(
                  'agents.form.advanced.systemPromptOverrideDescription',
                )}
                htmlFor="workflow-system-prompt-override"
              >
                <Switch
                  id="workflow-system-prompt-override"
                  checked={draft.allowPromptOverride}
                  onCheckedChange={(checked) =>
                    setDraft({ ...draft, allowPromptOverride: checked })
                  }
                />
              </SettingRow>
            </Card>
          </div>
          <Separator />
          <div className="flex justify-end gap-3 px-6 py-4">
            <Button
              type="button"
              variant="ghost"
              size="lg"
              shape="pill"
              onClick={() => onOpenChange(false)}
            >
              {t('agents.form.buttons.cancel')}
            </Button>
            <Button
              type="button"
              size="lg"
              shape="pill"
              disabled={!dirty}
              loading={saving}
              onClick={() => onSave({ ...draft, imageFile })}
            >
              {t('agents.form.buttons.save')}
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
