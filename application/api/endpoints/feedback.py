from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import uuid

from application.database import get_db
from application.core.models.feedback import ResponseFeedback
from application.core.models.conversations import Conversation

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

# Pydantic schemas
class FeedbackCreateRequest(BaseModel):
    """Request body for submitting feedback."""
    conversation_id: str
    response_id: str
    rating: int = Field(..., ge=1, le=5, description="Rating from 1 to 5")
    feedback_text: Optional[str] = Field(None, max_length=1000)
    
    class Config:
        schema_extra = {
            "example": {
                "conversation_id": "conv-123",
                "response_id": "resp-456",
                "rating": 5,
                "feedback_text": "This answer was very helpful and accurate!"
            }
        }

class FeedbackResponse(BaseModel):
    """Response after submitting feedback."""
    id: str
    conversation_id: str
    response_id: str
    rating: int
    feedback_text: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True

class FeedbackListResponse(BaseModel):
    """Response when listing feedback."""
    id: str
    conversation_id: str
    response_id: str
    rating: int
    feedback_text: Optional[str]
    created_at: datetime
    user_id: Optional[str]
    
    class Config:
        from_attributes = True

class FeedbackStats(BaseModel):
    """Statistics about feedback for a conversation."""
    total_feedback: int
    average_rating: float
    rating_distribution: dict  # {"1": count, "2": count, ...}
    positive_count: int  # ratings 4-5
    negative_count: int  # ratings 1-2

# Endpoints

@router.post("/", response_model=FeedbackResponse)
async def submit_feedback(
    request: FeedbackCreateRequest,
    db: Session = Depends(get_db)
):
    """
    Submit feedback for an AI response.
    
    Feedback is crucial for:
    - Understanding response quality from user perspective
    - Training and improving the model
    - Identifying systematic issues
    - Building evaluation datasets
    
    Args:
        request: Feedback data (conversation_id, response_id, rating, optional text)
        db: Database session
        
    Returns:
        FeedbackResponse with feedback ID and confirmation
    """
    # Verify conversation exists
    conversation = db.query(Conversation).filter(
        Conversation.id == request.conversation_id
    ).first()
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{request.conversation_id}' not found"
        )
    
    # Create feedback record
    feedback = ResponseFeedback(
        id=str(uuid.uuid4()),
        conversation_id=request.conversation_id,
        response_id=request.response_id,
        rating=request.rating,
        feedback_text=request.feedback_text,
        created_at=datetime.utcnow()
    )
    
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    
    return FeedbackResponse(
        id=feedback.id,
        conversation_id=feedback.conversation_id,
        response_id=feedback.response_id,
        rating=feedback.rating,
        feedback_text=feedback.feedback_text,
        created_at=feedback.created_at
    )

@router.get("/conversation/{conversation_id}", response_model=List[FeedbackListResponse])
async def get_conversation_feedback(
    conversation_id: str,
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000)
):
    """
    Get all feedback for a conversation.
    
    Args:
        conversation_id: The ID of the conversation
        db: Database session
        limit: Maximum number of records to return
        
    Returns:
        List of FeedbackListResponse objects
    """
    feedbacks = db.query(ResponseFeedback).filter(
        ResponseFeedback.conversation_id == conversation_id
    ).order_by(ResponseFeedback.created_at.desc()).limit(limit).all()
    
    return feedbacks

@router.get("/conversation/{conversation_id}/stats", response_model=FeedbackStats)
async def get_feedback_stats(
    conversation_id: str,
    db: Session = Depends(get_db)
):
    """
    Get statistics about feedback for a conversation.
    
    Args:
        conversation_id: The ID of the conversation
        db: Database session
        
    Returns:
        FeedbackStats with aggregated feedback data
    """
    feedbacks = db.query(ResponseFeedback).filter(
        ResponseFeedback.conversation_id == conversation_id
    ).all()
    
    if not feedbacks:
        return FeedbackStats(
            total_feedback=0,
            average_rating=0.0,
            rating_distribution={},
            positive_count=0,
            negative_count=0
        )
    
    # Calculate statistics
    ratings = [f.rating for f in feedbacks]
    total = len(ratings)
    average = sum(ratings) / total if total > 0 else 0
    
    # Rating distribution
    distribution = {}
    for i in range(1, 6):
        distribution[str(i)] = len([r for r in ratings if r == i])
    
    # Positive (4-5) and negative (1-2) counts
    positive = len([r for r in ratings if r >= 4])
    negative = len([r for r in ratings if r <= 2])
    
    return FeedbackStats(
        total_feedback=total,
        average_rating=round(average, 2),
        rating_distribution=distribution,
        positive_count=positive,
        negative_count=negative
    )

@router.delete("/feedback/{feedback_id}")
async def delete_feedback(
    feedback_id: str,
    db: Session = Depends(get_db)
):
    """
    Delete a feedback entry (for data privacy/correction).
    
    Args:
        feedback_id: The ID of the feedback to delete
        db: Database session
        
    Returns:
        Success message
    """
    feedback = db.query(ResponseFeedback).filter(
        ResponseFeedback.id == feedback_id
    ).first()
    
    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found"
        )
    
    db.delete(feedback)
    db.commit()
    
    return {"message": "Feedback deleted successfully"}

@router.get("/response/{response_id}/feedback")
async def get_response_feedback(
    response_id: str,
    db: Session = Depends(get_db)
):
    """
    Get all feedback for a specific response (across all conversations).
    
    Useful for analyzing how well a particular response performs.
    
    Args:
        response_id: The ID of the response
        db: Database session
        
    Returns:
        List of feedback entries
    """
    feedbacks = db.query(ResponseFeedback).filter(
        ResponseFeedback.response_id == response_id
    ).all()
    
    return feedbacks