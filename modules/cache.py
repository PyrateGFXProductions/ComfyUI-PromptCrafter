# Standard library imports
import os
import pickle
import shutil
import time

class DiskCache:
    """
    A persistent, size-limited, disk-based LRU (Least Recently Used) cache.

    This cache stores items as pickled files on disk. It automatically manages
    its total size, deleting the least recently used files when the size limit
    is exceeded.
    """
    def __init__(self, cache_dir, max_size_gb=2.0, eviction_batch_size=20):
        self.cache_dir = cache_dir
        self.max_size_bytes = max_size_gb * (1024 ** 3)
        self.eviction_batch_size = eviction_batch_size
        os.makedirs(self.cache_dir, exist_ok=True)

    def _key_to_filepath(self, key: str) -> str:
        """Converts a cache key into a valid filepath."""
        return os.path.join(self.cache_dir, f"{key}.pkl")

    def has(self, key: str) -> bool:
        """Checks if an item exists in the cache without updating its access time."""
        return os.path.exists(self._key_to_filepath(key))

    def get(self, key: str):
        """
        Retrieves an item from the cache.
        Returns the item if found, otherwise None.
        Updates the access time of the file, marking it as recently used.
        """
        filepath = self._key_to_filepath(key)
        if not os.path.exists(filepath):
            return None
        try:
            # Update access time by opening and closing the file
            with open(filepath, 'rb') as f:
                value = pickle.load(f)
            # In some OS, reading doesn't update atime, so we touch it.
            os.utime(filepath, None)
            return value
        except (pickle.UnpicklingError, EOFError, FileNotFoundError) as e:
            print(f"\033[93m[PromptCrafter Cache] Warning: Could not read cache file {filepath}. Removing it. Error: {e}\033[0m")
            self._safe_remove(filepath)
            return None

    def set(self, key: str, value: any):
        """
        Saves an item to the cache and runs the eviction policy if necessary.
        """
        filepath = self._key_to_filepath(key)
        try:
            with open(filepath, 'wb') as f:
                pickle.dump(value, f)
            self._enforce_size_limit()
        except (pickle.PicklingError, TypeError) as e:
            print(f"\033[91m[PromptCrafter Cache] Error: Could not serialize value for key '{key}'. Error: {e}\033[0m")

    def clear(self) -> int:
        """Removes all items from the cache directory."""
        count = 0
        for filename in os.listdir(self.cache_dir):
            filepath = os.path.join(self.cache_dir, filename)
            if self._safe_remove(filepath):
                count += 1
        return count

    def _enforce_size_limit(self):
        """Checks cache size and evicts least recently used items if over limit."""
        try:
            files = [os.path.join(self.cache_dir, f) for f in os.listdir(self.cache_dir) if f.endswith('.pkl')]
            
            # Sort files by access time (oldest first)
            files.sort(key=lambda f: os.path.getatime(f))
            
            total_size = sum(os.path.getsize(f) for f in files)

            if total_size > self.max_size_bytes:
                print(f"\033[94m[PromptCrafter Cache] Cache size ({total_size/1024**2:.2f}MB) exceeds limit. Evicting oldest items...\033[0m")
                # Evict in batches to be more efficient
                items_to_evict = files[:self.eviction_batch_size]
                for filepath in items_to_evict:
                    self._safe_remove(filepath)
        except Exception as e:
            # This is not a critical error, but we should log it.
            print(f"\033[91m[PromptCrafter Cache] Error: Could not enforce cache size limit. Error: {e}\033[0m")

    def _safe_remove(self, filepath: str) -> bool:
        """Safely removes a file, ignoring errors if it's already gone."""
        try:
            os.remove(filepath)
            return True
        except FileNotFoundError:
            return False # Already gone
        except OSError as e:
            print(f"\033[91m[PromptCrafter Cache] Error: Could not remove cache file {filepath}. Error: {e}\033[0m")
            return False

    @property
    def size(self) -> int:
        """Returns the number of items currently in the cache."""
        return len([name for name in os.listdir(self.cache_dir) if name.endswith('.pkl')])

    @property
    def max_size(self) -> str:
        """Returns the max size limit as a human-readable string."""
        return f"{self.max_size_bytes / (1024**3):.2f} GB"