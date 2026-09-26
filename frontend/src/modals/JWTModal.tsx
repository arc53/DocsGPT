import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Modal } from '../components/ui/modal';
import { ActiveState } from '../models/misc';

type JWTModalProps = {
  modalState: ActiveState;
  handleTokenSubmit: (enteredToken: string) => void;
};

export default function JWTModal({
  modalState,
  handleTokenSubmit,
}: JWTModalProps) {
  const { t } = useTranslation();
  const [jwtToken, setJwtToken] = useState<string>('');

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={() => {
        /* uncloseable by design; P1.7 revisits */
      }}
      isPerformingTask={true}
      title={t('modals.jwt.title')}
      footer={
        <Button
          type="button"
          size="lg"
          shape="pill"
          disabled={jwtToken.length === 0}
          onClick={handleTokenSubmit.bind(null, jwtToken)}
          data-testid="jwt-token-submit"
        >
          {t('modals.jwt.save')}
        </Button>
      }
    >
      <div data-testid="jwt-modal">
        <Input
          name="JWT Token"
          label={t('modals.jwt.label')}
          type="text"
          value={jwtToken}
          onChange={(e) => setJwtToken(e.target.value)}
          data-testid="jwt-token-input"
        />
      </div>
    </Modal>
  );
}
