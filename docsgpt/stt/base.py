from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional


class BaseSTT(ABC):
    @abstractmethod
    def transcribe(
        self,
        file_path: Path,
        language: Optional[str] = None,
        timestamps: bool = False,
        diarize: bool = False,
    ) -> Dict[str, Any]:
        pass
