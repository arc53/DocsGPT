import React from 'react';
import { useDispatch, useSelector } from 'react-redux';

import { Doc } from '../models/misc';
import { getDocs } from '../preferences/preferenceApi';
import {
  selectSelectedDocs,
  selectToken,
  setSelectedDocs,
  setSourceDocs,
} from '../preferences/preferenceSlice';

export default function useDefaultDocument() {
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const selectedDoc = useSelector(selectSelectedDocs);

  const fetchDocs = () => {
    getDocs(token).then((data) => {
      dispatch(setSourceDocs(data));
      if (!selectedDoc)
        Array.isArray(data) &&
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
