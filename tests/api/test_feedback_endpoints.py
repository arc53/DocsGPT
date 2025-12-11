import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from application.main import app
from application.database import SessionLocal
from application.core.models.conversations import Conversation
from application.core.models.feedback import ResponseFeedback

client = TestClient(app)

@pytest.fixture
def db():
    """Provide database session for tests."""
    db = SessionLocal()
    yield db
    db.close()

@pytest.fixture
def sample_conversation(db: Session) -> Conversation:
    """Create a sample conversation."""
    conv = Conversation(
        id="conv-test-123",
        title="Test Conversation"
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv

def test_submit_feedback_valid(sample_conversation: Conversation):
    """Test submitting valid feedback."""
    response = client.post(
        "/api/feedback",
        json={
            "conversation_id": sample_conversation.id,
            "response_id": "resp-456",
            "rating": 5,
            "feedback_text": "Excellent response!"
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["rating"] == 5
    assert data["feedback_text"] == "Excellent response!"
    assert "id" in data
    assert "created_at" in data

def test_submit_feedback_without_comment(sample_conversation: Conversation):
    """Test feedback without optional comment."""
    response = client.post(
        "/api/feedback",
        json={
            "conversation_id": sample_conversation.id,
            "response_id": "resp-789",
            "rating": 4
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["rating"] == 4
    assert data["feedback_text"] is None

def test_submit_feedback_invalid_rating():
    """Test that invalid ratings are rejected."""
    invalid_ratings = [0, 6, -1, 10, 100]
    
    for rating in invalid_ratings:
        response = client.post(
            "/api/feedback",
            json={
                "conversation_id": "conv-123",
                "response_id": "resp-456",
                "rating": rating
            }
        )
        
        assert response.status_code == 422  # Validation error

def test_submit_feedback_nonexistent_conversation():
    """Test error when conversation doesn't exist."""
    response = client.post(
        "/api/feedback",
        json={
            "conversation_id": "nonexistent",
            "response_id": "resp-456",
            "rating": 3
        }
    )
    
    assert response.status_code == 404

def test_get_conversation_feedback(db: Session, sample_conversation: Conversation):
    """Test retrieving feedback for a conversation."""
    # Submit multiple feedbacks
    feedbacks_data = [
        {"rating": 5, "text": "Great!"},
        {"rating": 4, "text": "Good"},
        {"rating": 2, "text": "Needs improvement"},
    ]
    
    for i, fb in enumerate(feedbacks_data):
        feedback = ResponseFeedback(
            id=f"feedback-{i}",
            conversation_id=sample_conversation.id,
            response_id=f"resp-{i}",
            rating=fb["rating"],
            feedback_text=fb["text"]
        )
        db.add(feedback)
    db.commit()
    
    response = client.get(
        f"/api/feedback/conversation/{sample_conversation.id}"
    )
    
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    assert data[0]["rating"] == 2  # Newest first (ordered desc)

def test_get_feedback_stats(db: Session, sample_conversation: Conversation):
    """Test feedback statistics endpoint."""
    # Create feedback with varied ratings
    ratings = [5, 5, 4, 3, 2, 1]
    for i, rating in enumerate(ratings):
        feedback = ResponseFeedback(
            id=f"stat-feedback-{i}",
            conversation_id=sample_conversation.id,
            response_id=f"resp-{i}",
            rating=rating
        )
        db.add(feedback)
    db.commit()
    
    response = client.get(
        f"/api/feedback/conversation/{sample_conversation.id}/stats"
    )
    
    assert response.status_code == 200
    stats = response.json()
    
    assert stats["total_feedback"] == 6
    assert stats["average_rating"] == 3.33  # (5+5+4+3+2+1)/6
    assert stats["positive_count"] == 3  # ratings 4-5
    assert stats["negative_count"] == 2  # ratings 1-2
    
    assert stats["rating_distribution"]["1"] == 1
    assert stats["rating_distribution"]["5"] == 2

def test_delete_feedback(db: Session, sample_conversation: Conversation):
    """Test deleting feedback."""
    feedback = ResponseFeedback(
        id="feedback-to-delete",
        conversation_id=sample_conversation.id,
        response_id="resp-xyz",
        rating=3
    )
    db.add(feedback)
    db.commit()
    
    response = client.delete(
        f"/api/feedback/feedback/{feedback.id}"
    )
    
    assert response.status_code == 200
    
    # Verify deleted
    deleted = db.query(ResponseFeedback).filter_by(id=feedback.id).first()
    assert deleted is None

def test_get_response_feedback(db: Session, sample_conversation: Conversation):
    """Test getting feedback for a specific response."""
    # Create feedback for same response in different conversations
    for i in range(3):
        conv = Conversation(id=f"conv-{i}", title=f"Conversation {i}")
        db.add(conv)
    db.commit()
    
    for i in range(3):
        feedback = ResponseFeedback(
            id=f"resp-fb-{i}",
            conversation_id=f"conv-{i}",
            response_id="same-response",  # Same response ID
            rating=4 + i
        )
        db.add(feedback)
    db.commit()
    
    response = client.get(
        "/api/feedback/response/same-response/feedback"
    )
    
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3