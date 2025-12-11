import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from application.main import app
from application.database import SessionLocal
from application.core.models.conversations import Conversation
from application.core.models.share import ConversationShare

client = TestClient(app)

@pytest.fixture
def db():
    """Provide a database session for tests."""
    db = SessionLocal()
    yield db
    db.close()

@pytest.fixture
def sample_conversation(db: Session) -> Conversation:
    """Create a sample conversation for testing."""
    conv = Conversation(
        id="test-conv-123",
        title="Test Conversation",
        is_private=False
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv

def test_create_share_success(sample_conversation: Conversation):
    """Test successfully creating a share."""
    response = client.post(
        f"/api/conversations/{sample_conversation.id}/share",
        json={
            "allow_prompting": True,
            "allow_editing": False
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "share_token" in data
    assert "share_url" in data
    assert data["permissions"]["allow_prompting"] is True
    assert data["permissions"]["allow_editing"] is False

def test_create_share_with_expiration(sample_conversation: Conversation):
    """Test creating a share with expiration."""
    response = client.post(
        f"/api/conversations/{sample_conversation.id}/share",
        json={
            "allow_prompting": False,
            "allow_editing": False,
            "expires_in_days": 7
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["expires_at"] is not None

def test_create_share_for_private_conversation(db: Session):
    """Test that private conversations can also be shared."""
    # Create a private conversation
    conv = Conversation(
        id="test-conv-private",
        title="Private Conversation",
        is_private=True
    )
    db.add(conv)
    db.commit()
    
    response = client.post(
        f"/api/conversations/{conv.id}/share",
        json={
            "allow_prompting": True,
            "allow_editing": True
        }
    )
    
    # Should succeed regardless of privacy setting
    assert response.status_code == 200
    assert response.json()["permissions"]["allow_prompting"] is True

def test_create_share_nonexistent_conversation():
    """Test error when creating share for non-existent conversation."""
    response = client.post(
        "/api/conversations/nonexistent-id/share",
        json={
            "allow_prompting": False,
            "allow_editing": False
        }
    )
    
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

def test_list_shares(db: Session, sample_conversation: Conversation):
    """Test listing shares for a conversation."""
    # Create multiple shares
    for i in range(3):
        share = ConversationShare(
            id=f"share-{i}",
            conversation_id=sample_conversation.id,
            share_token=f"token-{i}",
            allow_prompting=(i % 2 == 0),
            allow_editing=False
        )
        db.add(share)
    db.commit()
    
    response = client.get(f"/api/conversations/{sample_conversation.id}/shares")
    
    assert response.status_code == 200
    shares = response.json()
    assert len(shares) == 3
    assert shares[0]["allow_prompting"] is True
    assert shares[1]["allow_prompting"] is False

def test_delete_share(db: Session, sample_conversation: Conversation):
    """Test deleting a share."""
    share = ConversationShare(
        id="share-to-delete",
        conversation_id=sample_conversation.id,
        share_token="token-to-delete",
        allow_prompting=False,
        allow_editing=False
    )
    db.add(share)
    db.commit()
    
    response = client.delete(
        f"/api/conversations/{sample_conversation.id}/shares/{share.id}"
    )
    
    assert response.status_code == 200
    
    # Verify it's deleted
    db.refresh(db.session)
    deleted = db.query(ConversationShare).filter_by(id=share.id).first()
    assert deleted is None

def test_access_shared_conversation(db: Session, sample_conversation: Conversation):
    """Test accessing a shared conversation via share token."""
    share = ConversationShare(
        id="share-access",
        conversation_id=sample_conversation.id,
        share_token="unique-token-123",
        allow_prompting=True,
        allow_editing=False
    )
    db.add(share)
    db.commit()
    
    response = client.get("/api/share/unique-token-123")
    
    assert response.status_code == 200
    data = response.json()
    assert data["permissions"]["allow_prompting"] is True
    assert data["permissions"]["allow_editing"] is False

def test_access_expired_share(db: Session, sample_conversation: Conversation):
    """Test that expired shares cannot be accessed."""
    expired_time = datetime.utcnow() - timedelta(days=1)
    share = ConversationShare(
        id="expired-share",
        conversation_id=sample_conversation.id,
        share_token="expired-token",
        allow_prompting=False,
        allow_editing=False,
        expires_at=expired_time
    )
    db.add(share)
    db.commit()
    
    response = client.get("/api/share/expired-token")
    
    assert response.status_code == 410  # Gone
    assert "expired" in response.json()["detail"].lower()

def test_invalid_share_token():
    """Test accessing with invalid share token."""
    response = client.get("/api/share/invalid-token-xyz")
    
    assert response.status_code == 404