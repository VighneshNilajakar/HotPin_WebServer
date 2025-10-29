"""Storage manager for HotPin WebServer."""
import asyncio
import os
from typing import Dict, List, Optional
from .config import Config
from .utils import create_logger, cleanup_old_files

logger = create_logger(__name__)

class StorageManager:
    """Manages disk storage and resource cleanup."""
    
    def __init__(self):
        self.logger = create_logger(self.__class__.__name__)
        self.temp_dir = Config.TEMP_DIR
        self.cleanup_task: Optional[asyncio.Task] = None
        self.ensure_temp_directory()
    
    def ensure_temp_directory(self):
        """Ensure the temp directory exists."""
        os.makedirs(self.temp_dir, exist_ok=True)
        self.logger.info(f"Temp directory ensured: {self.temp_dir}")
    
    async def start_cleanup_task(self):
        """Start a background task to periodically clean up old files."""
        if self.cleanup_task is not None:
            self.cleanup_task.cancel()
        
        async def cleanup_loop():
            while True:
                try:
                    # Clean up old files based on grace period
                    cleaned_count = cleanup_old_files(self.temp_dir, Config.SESSION_GRACE_SEC)
                    if cleaned_count > 0:
                        self.logger.info(f"Cleaned up {cleaned_count} old files")
                    
                    await asyncio.sleep(300)  # Run cleanup every 5 minutes
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.logger.error(f"Error in storage cleanup task: {e}")
        
        self.cleanup_task = asyncio.create_task(cleanup_loop())
        self.logger.info("Started storage cleanup task")
    
    def stop_cleanup_task(self):
        """Stop the cleanup task."""
        if self.cleanup_task:
            self.cleanup_task.cancel()
            self.cleanup_task = None
            self.logger.info("Stopped storage cleanup task")
    
    def get_disk_usage(self) -> Dict[str, int]:
        """Get disk usage information for the temp directory."""
        total_size = 0
        file_count = 0
        
        for dirpath, dirnames, filenames in os.walk(self.temp_dir):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    size = os.path.getsize(filepath)
                    total_size += size
                    file_count += 1
                except OSError:
                    # Skip files that can't be accessed
                    continue
        
        return {
            "total_size_bytes": total_size,
            "file_count": file_count,
            "quota_bytes": Config.MAX_SESSION_DISK_MB * 1024 * 1024
        }
    
    def is_disk_quota_exceeded(self) -> bool:
        """Check if the overall disk quota is exceeded."""
        usage = self.get_disk_usage()
        return usage["total_size_bytes"] > usage["quota_bytes"]
    
    def cleanup_files_older_than(self, seconds: int) -> int:
        """Clean up files older than the specified number of seconds. Return number of files cleaned."""
        return cleanup_old_files(self.temp_dir, seconds)
    
    def get_file_size(self, file_path: str) -> int:
        """Get the size of a file."""
        try:
            return os.path.getsize(file_path)
        except OSError:
            return 0

# Global storage manager instance
storage_manager = StorageManager()