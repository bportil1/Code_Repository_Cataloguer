from sample_pkg.service import Service
import json


def run(name: str = "demo") -> Service:
    """Create and start a service."""
    service = Service(name)
    service.start()
    print(json.dumps({"name": name}))
    return service


if __name__ == "__main__":
    run()
