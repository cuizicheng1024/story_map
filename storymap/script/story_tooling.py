from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypeVar, cast


F = TypeVar("F", bound=Callable[..., object])


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str


def tool(name: str, description: str) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        setattr(func, "__tool__", ToolSpec(name=name, description=description))
        return cast(F, func)

    return decorator
