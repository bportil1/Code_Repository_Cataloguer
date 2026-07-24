from sample_pkg.service import Service
import json


def run(name: str = "demo") -> Service:
    """Create a service instance."""
    service = Service(name)
    service.start()
    return service
