"""Image handler for HotPin WebServer."""
import asyncio
import os
import time
from typing import Optional, Dict, Any
from PIL import Image
from .config import Config
from .utils import create_logger, create_temp_file, validate_image_file

logger = create_logger(__name__)

class ImageHandler:
    """Handles image uploads, validation, and storage for multimodal processing."""
    
    def __init__(self):
        self.logger = create_logger(self.__class__.__name__)
    
    async def handle_image_upload(self, session_id: str, image_data: bytes) -> Dict[str, Any]:
        """Handle an image upload for a session."""
        try:
            # Validate the image data
            validation_result = validate_image_file(
                image_data, 
                Config.MAX_IMAGE_SIZE_BYTES, 
                Config.IMAGE_MAX_DIMENSION
            )
            
            if not validation_result["valid"]:
                return {
                    "success": False,
                    "error": validation_result["error"]
                }
            
            # Create a temp file for the image
            temp_filename = f"image_{session_id}_{int(time.time())}.{validation_result['format'].lower()}"
            temp_path = os.path.join(Config.TEMP_DIR, temp_filename)
            
            # Save the image to temp file
            os.makedirs(os.path.dirname(temp_path), exist_ok=True)
            with open(temp_path, 'wb') as f:
                f.write(image_data)
            
            # Create a thumbnail for quick preview (optional)
            thumbnail_path = await self._create_thumbnail(temp_path)
            
            result = {
                "success": True,
                "filename": temp_filename,
                "path": temp_path,
                "thumbnail_path": thumbnail_path,
                "format": validation_result["format"],
                "dimensions": validation_result["dimensions"],
                "size": len(image_data)
            }
            
            self.logger.info(f"Image uploaded successfully for session {session_id}: {temp_path}")
            return result
            
        except OSError as e:
            self.logger.error(f"OS error handling image upload for session {session_id}: {e}")
            return {
                "success": False,
                "error": f"Failed to handle image upload (file system error): {str(e)}"
            }
        except Exception as e:
            self.logger.error(f"Error handling image upload for session {session_id}: {e}")
            return {
                "success": False,
                "error": f"Failed to handle image upload: {str(e)}"
            }
    
    async def _create_thumbnail(self, image_path: str, size: tuple = (256, 256)) -> Optional[str]:
        """Create a thumbnail for the given image."""
        try:
            with Image.open(image_path) as img:
                img.thumbnail(size, Image.Resampling.LANCZOS)
                
                # Create thumbnail path
                base_path, ext = os.path.splitext(image_path)
                thumbnail_path = f"{base_path}_thumb{ext}"
                
                img.save(thumbnail_path, format=img.format)
                return thumbnail_path
        except Exception as e:
            self.logger.error(f"Failed to create thumbnail for {image_path}: {e}")
            return None
    
    async def get_image_for_llm(self, image_path: str) -> Optional[bytes]:
        """Prepare image data for LLM processing (may include resizing if needed)."""
        try:
            if not os.path.exists(image_path):
                self.logger.error(f"Image file does not exist: {image_path}")
                return None
            
            # Check file size and resize if too large for LLM API
            file_size = os.path.getsize(image_path)
            
            # If file is too large, resize it (with quality reduction)
            if file_size > Config.MAX_IMAGE_SIZE_BYTES * 0.8:  # Use 80% of max as threshold
                resized_path = await self._resize_image(image_path)
                if resized_path:
                    with open(resized_path, 'rb') as f:
                        return f.read()
            
            # Otherwise, return original image
            with open(image_path, 'rb') as f:
                return f.read()
                
        except Exception as e:
            self.logger.error(f"Error preparing image for LLM {image_path}: {e}")
            return None
    
    async def _resize_image(self, image_path: str, max_size: int = 1024) -> Optional[str]:
        """Resize an image while maintaining aspect ratio."""
        try:
            with Image.open(image_path) as img:
                # Calculate new dimensions maintaining aspect ratio
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                
                # Create resized image path
                base_path, ext = os.path.splitext(image_path)
                resized_path = f"{base_path}_resized{ext}"
                
                # Save with reduced quality if JPEG to further reduce size
                if img.format == "JPEG":
                    img.save(resized_path, format="JPEG", quality=85, optimize=True)
                else:
                    img.save(resized_path, format=img.format)
                
                self.logger.info(f"Image resized from {image_path} to {resized_path}")
                return resized_path
        except Exception as e:
            self.logger.error(f"Failed to resize image {image_path}: {e}")
            return None
    
    async def cleanup_image_files(self, image_path: Optional[str], thumbnail_path: Optional[str]):
        """Clean up image files when no longer needed."""
        for path in [image_path, thumbnail_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    self.logger.info(f"Removed image file: {path}")
                except Exception as e:
                    self.logger.error(f"Failed to remove image file {path}: {e}")

# Global image handler instance
image_handler = ImageHandler()