import { useTranslation } from 'react-i18next';

import { FormField } from '@/components/ui/form-field';
import { Textarea } from '@/components/ui/textarea';

import { type NodePanelBodyProps } from './types';

/** Settings for a note node: its text. */
export default function NotePanel({
  node: selectedNode,
  onUpdate: handleUpdateNodeData,
}: NodePanelBodyProps) {
  const { t } = useTranslation();
  return (
    <FormField
      labelSurface="background"
      label={t('agents.workflow.builder.noteContent')}
    >
      <Textarea
        value={selectedNode.data.content || ''}
        onChange={(e) =>
          handleUpdateNodeData({
            content: e.target.value,
          })
        }
        rows={4}
        placeholder={t('agents.workflow.builder.noteContentPlaceholder')}
      />
    </FormField>
  );
}
