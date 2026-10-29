"""Generator interface shared by the mock and the real Comfy generator."""

from abc import ABC, abstractmethod


class ConfigurationError(Exception):
    """Raised when the app or a generator is configured incorrectly."""


class ImageGenerator(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> bytes:
        """Return PNG bytes for the prompt."""
