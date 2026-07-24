from dataclasses import dataclass


@dataclass
class Service:
    name: str

    def start(self) -> None:
        print(self.name)
