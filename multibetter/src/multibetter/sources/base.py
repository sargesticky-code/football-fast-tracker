from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import date

from multibetter.models import SourcePrediction


class SourceAdapter(ABC):
    name: str

    @abstractmethod
    def discover(self, day: date) -> Iterable[str]:
        """Return source-native fixture/detail URLs for the requested day."""
        raise NotImplementedError

    @abstractmethod
    def fetch_prediction(self, url: str) -> SourcePrediction:
        """Parse one source-native prediction page into the common schema."""
        raise NotImplementedError
