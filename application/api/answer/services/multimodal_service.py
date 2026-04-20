import json
import re
import logging
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from application.core.settings import settings

logger = logging.getLogger(__name__)

def normalize_question_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Standardizes incoming request data from the frontend.
    Ensures camelCase from React is converted to snake_case for Python logic.
    """
    if "imageBase64" in data and not data.get("image_base64"):
        data["image_base64"] = data.pop("imageBase64")
    if "imageMimeType" in data and not data.get("image_mime_type"):
        data["image_mime_type"] = data.pop("imageMimeType")

    question = data.get("question", "")
    
    # Handle legacy JSON-string payload format for backward compatibility
    if isinstance(question, str) and question.strip().startswith("{"):
        try:
            parsed = json.loads(question)
            if isinstance(parsed, dict):
                data["question"] = parsed.get("text", data.get("question", ""))
                if not data.get("image_base64") and parsed.get("imageBase64"):
                    data["image_base64"] = parsed.get("imageBase64")
                if not data.get("image_mime_type") and parsed.get("imageMimeType"):
                    data["image_mime_type"] = parsed.get("imageMimeType")
        except json.JSONDecodeError:
            pass
            
    return data

def extract_markdown_image_urls(text: str) -> List[str]:
    """Extracts image URLs from documentation chunks to allow the LLM to process visual context."""
    if not text:
        return []
    pattern = r"!\[.*?\]\((https?://[^\)]+)\)"
    return re.findall(pattern, text)

def build_multimodal_message_parts(
    question: str,
    image_base64: Optional[str] = None,
    docs_together: Optional[str] = None,
    image_mime_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Constructs a standardized message structure for multimodal LLMs."""
    message_parts: List[Dict[str, Any]] = []

    # 1. Add RAG context text
    if docs_together:
        message_parts.append({
            "type": "text",
            "text": f"Use the following retrieved context when relevant:\n\n{docs_together}"
        })
        
        # 2. Extract and append any images found within the RAG context
        rag_image_urls = extract_markdown_image_urls(docs_together)
        for url in rag_image_urls:
            message_parts.append({
                "type": "image_url",
                "image_url": {"url": url}
            })

    # 3. Add user question (defaulting to description if empty)
    message_parts.append({"type": "text", "text": question or "Please describe the provided image."})
    
    # 4. Add the user's uploaded Base64 image
    if image_base64:
        mime_type = image_mime_type or "image/jpeg"
        # Sanitize Base64 string to prevent double-header issues
        clean_b64 = image_base64.split(",")[-1] if "," in image_base64 else image_base64
        message_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{clean_b64}"}
        })

    return message_parts

def run_multimodal_completion(
    question: str,
    image_base64: Optional[str] = None,
    docs_together: Optional[str] = None,
    model_id: Optional[str] = None,
    image_mime_type: Optional[str] = None,
) -> str:
    """Routes the multimodal request to either Google Gemini or OpenAI based on settings."""
    
    provider = (settings.LLM_PROVIDER or "google").lower()
    google_key = settings.GOOGLE_API_KEY or settings.API_KEY
    openai_key = settings.OPENAI_API_KEY or settings.API_KEY
    
    # Default to a robust vision-capable model if none provided
    actual_model = model_id or settings.LLM_NAME or "gemini-3-flash-preview"

    try:
        if provider == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI
            
            if "gemini" not in actual_model.lower():
                actual_model = "gemini-3-flash-preview"
                
            logger.info(f"Routing multimodal request to Google Gemini ({actual_model})")

            llm = ChatGoogleGenerativeAI(
                model=actual_model,
                google_api_key=google_key,
                temperature=0
            )
        else:
            from langchain_openai import ChatOpenAI
            
            logger.info(f"Routing multimodal request to OpenAI ({actual_model})")
            llm = ChatOpenAI(
                model=actual_model,
                api_key=openai_key,
                base_url=settings.OPENAI_BASE_URL,
                temperature=0,
                thinking_budget=0,
            )

        # Execute completion
        response = llm.invoke([
            SystemMessage(content="You are DocsGPT, a helpful assistant. Use the provided text and images to answer user queries."),
            HumanMessage(content=build_multimodal_message_parts(
                question=question,
                image_base64=image_base64,
                docs_together=docs_together,
                image_mime_type=image_mime_type
            ))
        ])
        
        content = response.content
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict):
                    # Skip signature/thought parts, extract only text
                    if item.get("type") == "text" and item.get("text"):
                        text_parts.append(item["text"])
                elif isinstance(item, str):
                    text_parts.append(item)
            return "\n".join(text_parts) if text_parts else ""
        else:
            return str(content)
    
    except Exception as e:
        logger.error(f"Multimodal completion error: {str(e)}")
        return f"I encountered an error while processing the image: {str(e)}"