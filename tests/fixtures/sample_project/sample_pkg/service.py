from dataclasses import dataclass

from .utils import normalize_name


@dataclass
class Service:
    name: str

    def start(self) -> None:
        """Start the service."""
        print(normalize_name(self.name))
