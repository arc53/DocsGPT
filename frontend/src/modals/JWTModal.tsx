import React, { useState } from 'react';
import { useDispatch } from 'react-redux';

import Input from '../components/Input';
import { ActiveState } from '../models/misc';
import { setToken } from '../preferences/preferenceSlice';
import WrapperModal from './WrapperModal';

type JWTModalProps = {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
};

export default function JWTModal({ modalState, setModalState }: JWTModalProps) {
  const dispatch = useDispatch();
  const [jwtToken, setJwtToken] = useState<string>('');

  const handleSaveToken = () => {
    if (jwtToken) {
      localStorage.setItem('authToken', jwtToken);
      dispatch(setToken(jwtToken));
      setModalState('INACTIVE');
    }
  };

  if (modalState !== 'ACTIVE') return null;

  return (
    <WrapperModal close={() => setModalState('INACTIVE')} className="p-4">
      <div className="mb-6">
        <span className="text-lg text-jet dark:text-bright-gray">
          Add JWT Token
        </span>
      </div>
      <div className="relative mt-5 mb-4">
        <Input
          type="text"
          className="rounded-md"
          value={jwtToken}
          label="JWT Token"
          onChange={(e) => setJwtToken(e.target.value)}
          borderVariant="thin"
        />
      </div>
      <button
        disabled={jwtToken.length === 0}
        onClick={handleSaveToken}
        className="float-right mt-4 rounded-full bg-purple-30 px-5 py-2 text-sm text-white hover:bg-[#6F3FD1] disabled:opacity-50"
      >
        Save Token
      </button>
    </WrapperModal>
  );
}
