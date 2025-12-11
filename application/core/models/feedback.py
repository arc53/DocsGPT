from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from application.database import Base

class ResponseFeedback(Base):
    """Model representing user feedback on an AI response."""
    __tablename__ = "response_feedback"
    
    id = Column(String, primary_key=True, index=True)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False, index=True)
    response_id = Column(String, nullable=False, index=True)  # Could reference a responses table
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)  # Null for anonymous feedback
    
    # Feedback data
    rating = Column(Integer, nullable=False)  # 1-5 scale
    feedback_text = Column(Text, nullable=True)  # Optional detailed feedback
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    conversation = relationship("Conversation", back_populates="feedbacks")
    
    __table_args__ = (
        Index("ix_response_feedback_conversation_id", "conversation_id"),
        Index("ix_response_feedback_user_id", "user_id"),
        Index("ix_response_feedback_created_at", "created_at"),
    )