import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';

import conversationService from '../api/services/conversationService';
import MessageInput from '../components/MessageInput';
import { Button } from '../components/ui/button';
import { LoadingState } from '../components/ui/loading-state';
import { selectToken } from '../preferences/preferenceSlice';
import { AppDispatch } from '../store';
import { formatDateTime } from '../utils/dateTimeUtils';
import ConversationMessages from './ConversationMessages';
import {
  addQuery,
  fetchSharedAnswer,
  resetSharedConversation,
  selectClientAPIKey,
  selectDate,
  selectQueries,
  selectStatus,
  selectTitle,
  setClientApiKey,
  setFetchedData,
  setIdentifier,
  updateQuery,
} from './sharedConversationSlice';
import { selectSendableAttachments } from '../upload/uploadSlice';
import { Head as DocumentHead } from '../components/Head';

export const SharedConversation = () => {
  const navigate = useNavigate();
  const { identifier } = useParams(); //identifier is a uuid, not conversationId

  const token = useSelector(selectToken);
  const queries = useSelector(selectQueries);
  const title = useSelector(selectTitle);
  const date = useSelector(selectDate);
  const apiKey = useSelector(selectClientAPIKey);
  const status = useSelector(selectStatus);
  const sendableAttachments = useSelector(selectSendableAttachments);

  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();

  const [lastQueryReturnedErr, setLastQueryReturnedErr] = useState(false);
  // The share whose chat has loaded. Until then the page shows it loading:
  // the empty chat's hero (and its clickable suggestions) is not this page's.
  const [loadedFor, setLoadedFor] = useState<string | null>(null);

  useEffect(() => {
    if (queries.length) {
      queries[queries.length - 1].error && setLastQueryReturnedErr(true);
      queries[queries.length - 1].response && setLastQueryReturnedErr(false); //considering a query that initially returned error can later include a response property on retry
    }
  }, [queries[queries.length - 1]]);

  useEffect(() => {
    if (!identifier) return;
    let cancelled = false;
    // The page stays mounted from one share to the next: drop the last
    // share's chat rather than show it until this one arrives.
    dispatch(resetSharedConversation());
    dispatch(setIdentifier(identifier));
    conversationService
      .getSharedConversation(identifier, token)
      .then((res) => {
        if (res.status === 404 || res.status === 400) navigate('/pagenotfound');
        return res.json();
      })
      .then((data) => {
        if (cancelled) return;
        if (data.success) {
          dispatch(
            setFetchedData({
              queries: data.queries,
              title: data.title,
              date: formatDateTime(data.timestamp),
              identifier,
            }),
          );
          data.api_key && dispatch(setClientApiKey(data.api_key));
        }
      })
      .catch((error) => console.error('Failed to load the share:', error))
      .finally(() => {
        if (!cancelled) setLoadedFor(identifier);
      });
    return () => {
      cancelled = true;
    };
  }, [identifier]);

  const handleQuestionSubmission = (question?: string) => {
    if (question && status !== 'loading') {
      if (lastQueryReturnedErr) {
        // update last failed query with new prompt
        dispatch(
          updateQuery({
            index: queries.length - 1,
            query: {
              prompt: question,
            },
          }),
        );
        handleQuestion({
          question: queries[queries.length - 1].prompt,
          isRetry: true,
        });
      } else {
        handleQuestion({ question });
      }
    }
  };

  const handleQuestion = ({
    question,
    isRetry = false,
  }: {
    question: string;
    isRetry?: boolean;
  }) => {
    question = question.trim();
    if (question === '') return;

    const filesAttached = sendableAttachments;

    !isRetry &&
      dispatch(
        addQuery({
          prompt: question,
          attachments: filesAttached,
        }),
      ); //dispatch only new queries

    dispatch(fetchSharedAnswer({ question }));
  };

  return (
    <>
      <DocumentHead
        title={`DocsGPT | ${title}`}
        description={t('sharedConv.metaDescription')}
        ogTitle={title}
        ogDescription={t('sharedConv.metaDescription')}
        twitterCard="summary_large_image"
        twitterTitle={title}
        twitterDescription={t('sharedConv.metaDescription')}
      />
      <div className="bg-background flex h-full flex-col items-center justify-between gap-2 overflow-y-hidden">
        <div className="border-b-border w-full max-w-325 border-b p-2 md:w-11/12 lg:w-10/12 xl:w-9/12 2xl:w-8/12">
          {/* Each line keeps its height while the share loads, so the chat
              below doesn't move down when the title and date arrive. */}
          <h1 className="text-foreground min-h-10 text-4xl font-semibold">
            {title}
          </h1>
          <p className="text-muted-foreground text-sm">
            {t('sharedConv.subtitle')}{' '}
            <Button variant="link" size="text" asChild>
              <a href="/">DocsGPT</a>
            </Button>
          </p>
          <p className="text-muted-foreground min-h-5 text-sm">{date}</p>
        </div>
        {loadedFor === identifier ? (
          <ConversationMessages
            handleQuestion={handleQuestion}
            handleQuestionSubmission={handleQuestionSubmission}
            queries={queries}
            status={status}
            showHeroOnEmpty={false}
          />
        ) : (
          <LoadingState className="min-h-0 flex-1" />
        )}
        <div className="flex w-full max-w-290 flex-col items-center gap-4 pb-2 md:w-10/12 lg:w-9/12 xl:w-8/12 2xl:w-7/12">
          {apiKey ? (
            <div className="w-full px-2">
              <MessageInput
                onSubmit={(text) => {
                  handleQuestionSubmission(text);
                }}
                loading={status === 'loading'}
                showSourceButton={false}
                showToolButton={false}
              />
            </div>
          ) : (
            <Button
              type="button"
              onClick={() => navigate('/')}
              size="lg"
              shape="pill"
              className="mb-14 w-fit sm:mb-0"
            >
              {t('sharedConv.button')}
            </Button>
          )}

          <p className="text-muted-foreground hidden w-screen self-center bg-transparent py-2 text-center text-xs md:inline md:w-full">
            {t('sharedConv.meta')}
          </p>
        </div>
      </div>
    </>
  );
};
