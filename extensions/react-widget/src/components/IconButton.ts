import styled from 'styled-components';
import { focusRing, radii } from './tokens';

/** ghost-muted icon-sm: 32px, rounded-md, accent hover. */
export const IconButton = styled.button`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  margin: 0;
  padding: 0;
  border: none;
  border-radius: ${radii.md};
  background-color: transparent;
  color: ${(props) => props.theme.mutedForeground};
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    color 0.15s ease;

  &:hover,
  &[aria-pressed='true'] {
    background-color: ${(props) => props.theme.accent};
    color: ${(props) => props.theme.foreground};
  }

  ${focusRing}
`;
