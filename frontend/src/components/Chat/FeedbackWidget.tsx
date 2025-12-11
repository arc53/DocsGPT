import React, { useState, useCallback } from 'react';
import {
  Box,
  IconButton,
  TextField,
  Button,
  Typography,
  Tooltip,
  Collapse,
  Alert,
  CircularProgress,
  Paper,
} from '@mui/material';
import ThumbUpIcon from '@mui/icons-material/ThumbUp';
import ThumbDownIcon from '@mui/icons-material/ThumbDown';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import { api } from '@/services/api';

interface FeedbackWidgetProps {
  conversationId: string;
  responseId: string;
  onFeedbackSubmitted?: (rating: number) => void;
}

type Rating = 1 | 5 | null;

interface FeedbackState {
  rating: Rating;
  showComment: boolean;
  comment: string;
  submitted: boolean;
  loading: boolean;
  error: string | null;
}

const initialState: FeedbackState = {
  rating: null,
  showComment: false,
  comment: '',
  submitted: false,
  loading: false,
  error: null,
};

export const FeedbackWidget: React.FC<FeedbackWidgetProps> = ({
  conversationId,
  responseId,
  onFeedbackSubmitted,
}) => {
  const [state, setState] = useState<FeedbackState>(initialState);

  const handleRating = (rating: Rating) => {
    setState((prev) => ({
      ...prev,
      rating,
      showComment: rating !== null,
      error: null,
    }));
  };

  const handleCommentChange = (text: string) => {
    setState((prev) => ({
      ...prev,
      comment: text,
    }));
  };

  const handleSubmit = useCallback(async () => {
    if (state.rating === null) return;

    setState((prev) => ({ ...prev, loading: true, error: null }));

    try {
      await api.post('/feedback', {
        conversation_id: conversationId,
        response_id: responseId,
        rating: state.rating,
        feedback_text: state.comment || null,
      });

      setState((prev) => ({
        ...prev,
        submitted: true,
        loading: false,
      }));

      if (onFeedbackSubmitted) {
        onFeedbackSubmitted(state.rating);
      }

      // Reset after 3 seconds
      setTimeout(() => {
        setState(initialState);
      }, 3000);
    } catch (error: any) {
      setState((prev) => ({
        ...prev,
        loading: false,
        error: error.response?.data?.detail || 'Failed to submit feedback',
      }));
    }
  }, [
    state.rating,
    state.comment,
    conversationId,
    responseId,
    onFeedbackSubmitted,
  ]);

  const handleCancel = () => {
    setState(initialState);
  };

  // Render success state
  if (state.submitted) {
    return (
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          py: 1,
          px: 2,
          bgcolor: '#f0f7f4',
          borderRadius: 1,
          animation: 'fadeIn 0.3s ease-in',
        }}
      >
        <CheckCircleIcon sx={{ color: '#4caf50', fontSize: 20 }} />
        <Typography
          variant="caption"
          sx={{ color: '#4caf50', fontWeight: 500 }}
        >
          Thank you for your feedback!
        </Typography>
      </Box>
    );
  }

  // Render initial state
  if (state.rating === null) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, py: 1 }}>
        <Typography variant="caption" color="textSecondary" sx={{ mr: 1 }}>
          Was this helpful?
        </Typography>

        <Tooltip title="Helpful">
          <IconButton
            size="small"
            onClick={() => handleRating(5)}
            sx={{
              '&:hover': { bgcolor: '#e8f5e9' },
            }}
          >
            <ThumbUpIcon fontSize="small" sx={{ color: '#757575' }} />
          </IconButton>
        </Tooltip>

        <Tooltip title="Not helpful">
          <IconButton
            size="small"
            onClick={() => handleRating(1)}
            sx={{
              '&:hover': { bgcolor: '#ffebee' },
            }}
          >
            <ThumbDownIcon fontSize="small" sx={{ color: '#757575' }} />
          </IconButton>
        </Tooltip>
      </Box>
    );
  }

  // Render feedback form
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 2,
        bgcolor: state.rating === 5 ? '#f0f7f4' : '#fff8e1',
        borderColor: state.rating === 5 ? '#4caf50' : '#ff9800',
        borderWidth: 1,
        animation: 'slideDown 0.2s ease-out',
      }}
    >
      {state.error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {state.error}
        </Alert>
      )}

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
        <Typography variant="body2" sx={{ fontWeight: 500 }}>
          {state.rating === 5
            ? '👍 Glad this was helpful!'
            : "👎 We're sorry this wasn't helpful"}
        </Typography>
      </Box>

      <Collapse in={state.showComment} timeout="auto" unmountOnExit>
        <Box sx={{ mb: 2 }}>
          <TextField
            fullWidth
            multiline
            rows={2}
            placeholder="Tell us what could be improved... (optional)"
            value={state.comment}
            onChange={(e) => handleCommentChange(e.target.value)}
            size="small"
            variant="outlined"
            maxLength={1000}
            sx={{ mb: 1 }}
          />
          <Typography variant="caption" color="textSecondary">
            {state.comment.length}/1000 characters
          </Typography>
        </Box>
      </Collapse>

      <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
        <Button size="small" onClick={handleCancel}>
          Cancel
        </Button>
        <Button
          size="small"
          variant="contained"
          color={state.rating === 5 ? 'success' : 'warning'}
          onClick={handleSubmit}
          disabled={state.loading}
        >
          {state.loading ? <CircularProgress size={16} sx={{ mr: 1 }} /> : null}
          Submit
        </Button>
      </Box>

      <style>{`
        @keyframes slideDown {
          from {
            opacity: 0;
            transform: translateY(-8px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
        @keyframes fadeIn {
          from {
            opacity: 0;
          }
          to {
            opacity: 1;
          }
        }
      `}</style>
    </Paper>
  );
};

export default FeedbackWidget;
