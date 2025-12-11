from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from application.database import Base

class ConversationShare(Base):
    """Model representing a shared conversation."""
    __tablename__ = "conversation_shares"
    
    id = Column(String, primary_key=True, index=True)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False, index=True)
    share_token = Column(String, unique=True, nullable=False, index=True)
    
    # Permission flags
    allow_prompting = Column(Boolean, default=False, nullable=False)
    allow_editing = Column(Boolean, default=False, nullable=False)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)  # Optional expiration
    
    # Relationships
    conversation = relationship("Conversation", back_populates="shares")
    
    __table_args__ = (
        Index("ix_conversation_shares_token", "share_token"),
        Index("ix_conversation_shares_conversation_id", "conversation_id"),
    )