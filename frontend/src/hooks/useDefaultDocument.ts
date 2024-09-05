import React from 'react';
import { useDispatch, useSelector } from 'react-redux';

import { Doc, getDocs } from '../preferences/preferenceApi';
import {
  selectSelectedDocs,
  setSelectedDocs,
  setSourceDocs,
} from '../preferences/preferenceSlice';

export default function useDefaultDocument() {
  const dispatch = useDispatch();
  const selectedDoc = useSelector(selectSelectedDocs);

  const fetchDocs = () => {
    getDocs().then((data) => {
      dispatch(setSourceDocs(data));
      if (!selectedDoc)
        data?.forEach((doc: Doc) => {
          if (doc.model && doc.name === 'default') {
            dispatch(setSelectedDocs(doc));
          }
        });
    });
  };

  React.useEffect(() => {
    fetchDocs();
  }, []);
}
