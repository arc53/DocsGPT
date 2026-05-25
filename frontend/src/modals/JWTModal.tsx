import React, { useState } from 'react';

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
  const [jwtToken, setJwtToken] = useState<string>('');

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={() => {
        /* uncloseable by design; P1.7 revisits */
      }}
      isPerformingTask={true}
      title="Add JWT Token"
    >
      <div data-testid="jwt-modal">
        <div className="relative mt-5 mb-4">
          <Input
            name="JWT Token"
            type="text"
            className="rounded-md"
            value={jwtToken}
            onChange={(e) => setJwtToken(e.target.value)}
            data-testid="jwt-token-input"
          />
        </div>
        <Button
          type="button"
          disabled={jwtToken.length === 0}
          onClick={handleTokenSubmit.bind(null, jwtToken)}
          className="float-right mt-4 rounded-3xl px-5"
          data-testid="jwt-token-submit"
        >
          Save Token
        </Button>
      </div>
    </Modal>
  );
}
