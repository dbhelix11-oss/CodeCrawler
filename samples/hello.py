"""A small sample file to crawl with CodeCrawler."""

import math
from dataclasses import dataclass


GREETING = "hello"


@dataclass
class Circle:
    radius: float

    def area(self) -> float:
        return math.pi * self.radius ** 2


def greet(name, *, loud=False):
    message = f"{GREETING}, {name}!"
    if loud:
        message = message.upper()
    return message


def main() -> None:
    shapes = [Circle(r) for r in (1, 2, 3)]
    areas = {s.radius: s.area() for s in shapes}
    for radius, size in areas.items():
        print(greet(f"circle-{radius}", loud=size > 10))


if __name__ == "__main__":
    main()
