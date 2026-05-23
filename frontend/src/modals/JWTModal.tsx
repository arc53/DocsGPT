import React, { useState } from 'react';

import Input from '../components/Input';
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
            borderVariant="thin"
            data-testid="jwt-token-input"
          />
        </div>
        <button
          disabled={jwtToken.length === 0}
          onClick={handleTokenSubmit.bind(null, jwtToken)}
          className="bg-primary float-right mt-4 rounded-full px-5 py-2 text-sm text-white hover:bg-[#6F3FD1] disabled:opacity-50"
          data-testid="jwt-token-submit"
        >
          Save Token
        </button>
      </div>
    </Modal>
  );
}
