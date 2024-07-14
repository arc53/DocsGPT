import React from 'react';
import { Doc } from '../models/misc';
import Exit from '../assets/exit.svg';
import { useDispatch } from 'react-redux';
import { setSelectedDocs } from '../preferences/preferenceSlice';

export function ConversationSourceList({ docs }: TConversationSourceListProps) {
  const dispatch = useDispatch();
  return (
    <div className="flex flex-row">
      {docs &&
        docs.map((doc, idx) => {
          return (
            <div
              className={`flex max-w-xs flex-row rounded-[28px] bg-[#D7EBFD] px-4 py-1 sm:max-w-sm md:max-w-md`}
              key={idx}
            >
              <img
                src={Exit}
                alt="Remove"
                className="mr-2 mt-1 h-3 w-3 cursor-pointer hover:opacity-50"
                onClick={() => dispatch(setSelectedDocs(null))}
              />
              {doc.name}
            </div>
          );
        })}
    </div>
  );
}

type TConversationSourceListProps = {
  docs: Doc[];
};
