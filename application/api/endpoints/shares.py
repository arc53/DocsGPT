from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta
import uuid

from application.database import get_db
from application.core.models.share import ConversationShare
from application.core.models.conversations import Conversation

router = APIRouter(prefix="/api/conversations", tags=["shares"])

# Pydantic schemas
class ShareCreateRequest(BaseModel):
    """Request body for creating a conversation share."""
    allow_prompting: bool = False
    allow_editing: bool = False
    expires_in_days: Optional[int] = None  # Days until expiration
    
    class Config:
        schema_extra = {
            "example": {
                "allow_prompting": True,
                "allow_editing": False,
                "expires_in_days": 30
            }
        }

class ShareResponse(BaseModel):
    """Response when creating a share."""
    share_token: str
    share_url: str
    permissions: dict
    created_at: datetime
    expires_at: Optional[datetime]
    
    class Config:
        from_attributes = True

class ShareListResponse(BaseModel):
    """Response when listing shares."""
    id: str
    share_token: str
    conversation_id: str
    allow_prompting: bool
    allow_editing: bool
    created_at: datetime
    expires_at: Optional[datetime]
    
    class Config:
        from_attributes = True

# Endpoints

@router.post("/{conversation_id}/share", response_model=ShareResponse)
async def create_share(
    conversation_id: str,
    request: ShareCreateRequest,
    db: Session = Depends(get_db)
):
    """
    Create a shareable link for a conversation.
    
    The share functionality is independent of the conversation's privacy settings.
    The sharer can specify which permissions are granted to recipients.
    
    Args:
        conversation_id: The ID of the conversation to share
        request: Share creation parameters
        db: Database session
        
    Returns:
        ShareResponse with token and permissions
        
    Raises:
        HTTPException: 404 if conversation not found
    """
    # Verify conversation exists
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation with ID '{conversation_id}' not found"
        )
    
    # Generate unique share token
    share_token = str(uuid.uuid4())
    
    # Calculate expiration date if specified
    expires_at = None
    if request.expires_in_days:
        expires_at = datetime.utcnow() + timedelta(days=request.expires_in_days)
    
    # Create share record
    share = ConversationShare(
        id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        share_token=share_token,
        allow_prompting=request.allow_prompting,
        allow_editing=request.allow_editing,
        created_at=datetime.utcnow(),
        expires_at=expires_at
    )
    
    db.add(share)
    db.commit()
    db.refresh(share)
    
    return ShareResponse(
        share_token=share_token,
        share_url=f"/share/{share_token}",
        permissions={
            "allow_prompting": share.allow_prompting,
            "allow_editing": share.allow_editing
        },
        created_at=share.created_at,
        expires_at=share.expires_at
    )

@router.get("/{conversation_id}/shares", response_model=List[ShareListResponse])
async def list_shares(
    conversation_id: str,
    db: Session = Depends(get_db)
):
    """
    List all shares for a conversation.
    
    Args:
        conversation_id: The ID of the conversation
        db: Database session
        
    Returns:
        List of ShareListResponse objects
    """
    # Verify conversation exists
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation with ID '{conversation_id}' not found"
        )
    
    shares = db.query(ConversationShare).filter(
        ConversationShare.conversation_id == conversation_id
    ).all()
    
    return shares

@router.delete("/{conversation_id}/shares/{share_id}")
async def delete_share(
    conversation_id: str,
    share_id: str,
    db: Session = Depends(get_db)
):
    """
    Revoke a share (delete it).
    
    Args:
        conversation_id: The ID of the conversation
        share_id: The ID of the share to delete
        db: Database session
        
    Returns:
        Success message
    """
    share = db.query(ConversationShare).filter(
        ConversationShare.id == share_id,
        ConversationShare.conversation_id == conversation_id
    ).first()
    
    if not share:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share not found"
        )
    
    db.delete(share)
    db.commit()
    
    return {"message": "Share revoked successfully"}

@router.get("/share/{share_token}")
async def access_shared_conversation(
    share_token: str,
    db: Session = Depends(get_db)
):
    """
    Access a shared conversation via share token.
    
    Args:
        share_token: The share token
        db: Database session
        
    Returns:
        Conversation data (limited by permissions)
    """
    share = db.query(ConversationShare).filter(
        ConversationShare.share_token == share_token
    ).first()
    
    if not share:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid share token"
        )
    
    # Check expiration
    if share.expires_at and datetime.utcnow() > share.expires_at:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This share link has expired"
        )
    
    conversation = db.query(Conversation).filter(
        Conversation.id == share.conversation_id
    ).first()
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )
    
    return {
        "conversation": conversation,
        "permissions": {
            "allow_prompting": share.allow_prompting,
            "allow_editing": share.allow_editing
        }
    }