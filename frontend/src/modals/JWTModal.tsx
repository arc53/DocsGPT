import React, { useState } from 'react';

import Input from '../components/Input';
import { ActiveState } from '../models/misc';
import WrapperModal from './WrapperModal';

type JWTModalProps = {
  modalState: ActiveState;
  handleTokenSubmit: (enteredToken: string) => void;
};

export default function JWTModal({
  modalState,
  handleTokenSubmit,
}: JWTModalProps) {
  const [jwtToken, setJwtToken] = useState<string>('');

  if (modalState !== 'ACTIVE') return null;

  return (
    <WrapperModal
      className="p-4"
      isPerformingTask={true}
      close={() => undefined}
    >
      <div className="mb-6">
        <span className="text-jet dark:text-bright-gray text-lg">
          Add JWT Token
        </span>
      </div>
      <div className="relative mt-5 mb-4">
        <Input
          name="JWT Token"
          type="text"
          className="rounded-md"
          value={jwtToken}
          onChange={(e) => setJwtToken(e.target.value)}
          borderVariant="thin"
        />
      </div>
      <button
        disabled={jwtToken.length === 0}
        onClick={handleTokenSubmit.bind(null, jwtToken)}
        className="bg-purple-30 float-right mt-4 rounded-full px-5 py-2 text-sm text-white hover:bg-[#6F3FD1] disabled:opacity-50"
      >
        Save Token
      </button>
    </WrapperModal>
  );
}
