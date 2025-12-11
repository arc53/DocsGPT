import React, { useState, useEffect } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  FormControlLabel,
  Checkbox,
  Box,
  Typography,
  IconButton,
  Tooltip,
  List,
  ListItem,
  ListItemText,
  Alert,
  CircularProgress,
} from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import DeleteIcon from '@mui/icons-material/Delete';
import ShareIcon from '@mui/icons-material/Share';
import { api } from '@/services/api';

interface ShareDialogProps {
  conversationId: string;
  onClose: () => void;
  open: boolean;
}

interface Share {
  id: string;
  share_token: string;
  allow_prompting: boolean;
  allow_editing: boolean;
  created_at: string;
  expires_at?: string;
}

export const ShareDialog: React.FC<ShareDialogProps> = ({
  conversationId,
  onClose,
  open,
}) => {
  const [allowPrompting, setAllowPrompting] = useState(false);
  const [allowEditing, setAllowEditing] = useState(false);
  const [expiresInDays, setExpiresInDays] = useState<number | ''>('');
  const [shares, setShares] = useState<Share[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedToken, setCopiedToken] = useState<string | null>(null);

  // Load existing shares when dialog opens
  useEffect(() => {
    if (open) {
      loadShares();
    }
  }, [open, conversationId]);

  const loadShares = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.get(`/conversations/${conversationId}/shares`);
      setShares(response.data);
    } catch (err: any) {
      setError(
        'Failed to load shares: ' + (err.response?.data?.detail || err.message),
      );
    } finally {
      setLoading(false);
    }
  };

  const handleCreateShare = async () => {
    setLoading(true);
    setError(null);
    try {
      const payload: any = {
        allow_prompting: allowPrompting,
        allow_editing: allowEditing,
      };

      if (expiresInDays) {
        payload.expires_in_days = Number(expiresInDays);
      }

      const response = await api.post(
        `/conversations/${conversationId}/share`,
        payload,
      );

      // Reload shares to show the new one
      await loadShares();

      // Reset form
      setAllowPrompting(false);
      setAllowEditing(false);
      setExpiresInDays('');
    } catch (err: any) {
      setError(
        'Failed to create share: ' +
          (err.response?.data?.detail || err.message),
      );
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteShare = async (shareId: string) => {
    try {
      await api.delete(`/conversations/${conversationId}/shares/${shareId}`);
      // Reload shares
      await loadShares();
    } catch (err: any) {
      setError(
        'Failed to delete share: ' +
          (err.response?.data?.detail || err.message),
      );
    }
  };

  const handleCopyShareUrl = (shareToken: string) => {
    const shareUrl = `${window.location.origin}/share/${shareToken}`;
    navigator.clipboard.writeText(shareUrl);
    setCopiedToken(shareToken);
    setTimeout(() => setCopiedToken(null), 2000);
  };

  const formatPermissions = (share: Share) => {
    const perms = [];
    if (share.allow_prompting) perms.push('Can prompt');
    if (share.allow_editing) perms.push('Can edit');
    if (perms.length === 0) perms.push('View only');
    return perms.join(', ');
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        <Box display="flex" alignItems="center" gap={1}>
          <ShareIcon />
          Share Conversation
        </Box>
      </DialogTitle>

      <DialogContent>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {/* Create New Share Section */}
        <Box sx={{ mb: 3 }}>
          <Typography variant="subtitle2" sx={{ mb: 2, fontWeight: 600 }}>
            Create New Share
          </Typography>

          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <FormControlLabel
              control={
                <Checkbox
                  checked={allowPrompting}
                  onChange={(e) => setAllowPrompting(e.target.checked)}
                />
              }
              label="Allow recipients to send prompts"
            />

            <FormControlLabel
              control={
                <Checkbox
                  checked={allowEditing}
                  onChange={(e) => setAllowEditing(e.target.checked)}
                />
              }
              label="Allow recipients to edit conversation"
            />

            <TextField
              type="number"
              label="Expiration (days)"
              placeholder="Leave empty for no expiration"
              value={expiresInDays}
              onChange={(e) =>
                setExpiresInDays(
                  e.target.value === '' ? '' : parseInt(e.target.value),
                )
              }
              inputProps={{ min: 1, max: 365 }}
              size="small"
            />
          </Box>
        </Box>

        {/* Existing Shares Section */}
        <Box>
          <Typography variant="subtitle2" sx={{ mb: 2, fontWeight: 600 }}>
            Active Shares ({shares.length})
          </Typography>

          {loading ? (
            <Box display="flex" justifyContent="center" p={2}>
              <CircularProgress size={24} />
            </Box>
          ) : shares.length === 0 ? (
            <Typography variant="body2" color="textSecondary">
              No active shares yet
            </Typography>
          ) : (
            <List sx={{ maxHeight: 300, overflow: 'auto' }}>
              {shares.map((share) => (
                <ListItem
                  key={share.id}
                  sx={{
                    border: '1px solid #eee',
                    borderRadius: 1,
                    mb: 1,
                    py: 1,
                  }}
                >
                  <ListItemText
                    primary={
                      <Box display="flex" alignItems="center" gap={1}>
                        <code
                          style={{
                            fontSize: '0.75rem',
                            backgroundColor: '#f5f5f5',
                            padding: '2px 6px',
                            borderRadius: 3,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            maxWidth: '200px',
                          }}
                        >
                          {share.share_token.substring(0, 12)}...
                        </code>
                        <Tooltip
                          title={
                            copiedToken === share.share_token
                              ? 'Copied!'
                              : 'Copy link'
                          }
                        >
                          <IconButton
                            size="small"
                            onClick={() =>
                              handleCopyShareUrl(share.share_token)
                            }
                          >
                            <ContentCopyIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </Box>
                    }
                    secondary={
                      <>
                        <Typography variant="caption" display="block">
                          Permissions: {formatPermissions(share)}
                        </Typography>
                        <Typography variant="caption" display="block">
                          Created:{' '}
                          {new Date(share.created_at).toLocaleDateString()}
                          {share.expires_at &&
                            ` • Expires: ${new Date(share.expires_at).toLocaleDateString()}`}
                        </Typography>
                      </>
                    }
                  />
                  <Tooltip title="Delete share">
                    <IconButton
                      edge="end"
                      size="small"
                      onClick={() => handleDeleteShare(share.id)}
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </ListItem>
              ))}
            </List>
          )}
        </Box>
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose}>Close</Button>
        <Button
          onClick={handleCreateShare}
          variant="contained"
          disabled={loading}
        >
          {loading ? <CircularProgress size={20} /> : 'Create Share'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default ShareDialog;
