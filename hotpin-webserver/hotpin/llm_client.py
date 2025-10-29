"""LLM client for HotPin WebServer using Groq API."""
import asyncio
import json
import time
from typing import Optional, Dict, Any, List
import httpx
from .config import Config
from .utils import create_logger

logger = create_logger(__name__)

class LLMClient:
    """Client for interacting with Groq's multimodal API."""
    
    def __init__(self):
        self.logger = create_logger(self.__class__.__name__)
        self.api_key = Config.GROQ_API_KEY
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
        self.default_model = "meta-llama/llama-4-maverick-17b-128e-instruct"
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),  # 60 second timeout
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
    
    async def chat_with_image_and_text(
        self, 
        text: str, 
        image_data: Optional[bytes] = None, 
        conversation_history: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None
    ) -> Optional[str]:
        """Send multimodal request with text and optional image to Groq API."""
        
        # Build the messages array
        messages = []
        
        # Add system prompt if provided
        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })
        else:
            # Default system prompt
            messages.append({
                "role": "system",
                "content": "You are a helpful AI assistant. Respond concisely and use natural language."
            })
        
        # Add conversation history if provided
        if conversation_history:
            for turn in conversation_history:
                messages.append({
                    "role": turn["role"],
                    "content": turn["content"]
                })
        
        # Prepare content for current message
        current_content = []
        
        # Add image if provided
        if image_data:
            # Convert image to base64 for API
            import base64
            image_base64 = base64.b64encode(image_data).decode('utf-8')
            
            current_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_base64}"
                }
            })
        
        # Add text content
        current_content.append({
            "type": "text",
            "text": text
        })
        
        # Add user message with content
        messages.append({
            "role": "user",
            "content": current_content
        })
        
        # Prepare the payload
        payload = {
            "model": self.default_model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1024,
            "stream": False
        }
        
        # Make the API call with retry logic
        for attempt in range(Config.GROQ_RETRY_ATTEMPTS):
            try:
                start_time = time.time()
                
                response = await self.client.post(
                    self.base_url,
                    json=payload
                )
                
                response.raise_for_status()
                result = response.json()
                
                duration = time.time() - start_time
                self.logger.info(f"LLM call completed in {duration:.2f}s")
                
                # Extract the response text
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]
                    self.logger.debug(f"LLM response: {content[:100]}...")
                    return content
                else:
                    self.logger.error("No choices in LLM response")
                    return None
                    
            except httpx.HTTPStatusError as e:
                self.logger.error(f"HTTP error on attempt {attempt + 1}: {e}")
                if e.response.status_code == 401:
                    self.logger.error("Authentication failed - check GROQ_API_KEY")
                    break  # Don't retry auth errors
                elif e.response.status_code == 429:
                    self.logger.warning("Rate limited, waiting before retry...")
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                elif attempt == Config.GROQ_RETRY_ATTEMPTS - 1:
                    self.logger.error("All retry attempts failed")
                    # Try fallback model if configured
                    if Config.GROQ_FALLBACK_MODEL:
                        self.logger.info(f"Trying fallback model: {Config.GROQ_FALLBACK_MODEL}")
                        payload["model"] = Config.GROQ_FALLBACK_MODEL
                        try:
                            response = await self.client.post(
                                self.base_url,
                                json=payload
                            )
                            response.raise_for_status()
                            result = response.json()
                            
                            if "choices" in result and len(result["choices"]) > 0:
                                return result["choices"][0]["message"]["content"]
                        except Exception as fallback_error:
                            self.logger.error(f"Fallback model also failed: {fallback_error}")
            
            except httpx.RequestError as e:
                self.logger.error(f"Request error on attempt {attempt + 1}: {e}")
                if attempt < Config.GROQ_RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
            except Exception as e:
                self.logger.error(f"Unexpected error on attempt {attempt + 1}: {e}")
                if attempt < Config.GROQ_RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
        
        return None
    
    async def simple_chat(self, text: str, conversation_history: Optional[List[Dict[str, str]]] = None) -> Optional[str]:
        """Send a simple text-only request to the LLM."""
        return await self.chat_with_image_and_text(
            text=text,
            image_data=None,
            conversation_history=conversation_history
        )

# Global LLM client instance
llm_client = LLMClient()