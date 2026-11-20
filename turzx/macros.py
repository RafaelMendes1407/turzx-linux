"""Declarative display rules stored with an element's theme."""

from dataclasses import dataclass, replace
import math
import operator

from .emojis import EMOJIS
from .metrics import is_numeric, raw_value


COMPARISONS = {
    ">=": operator.ge, ">": operator.gt, "<=": operator.le,
    "<": operator.lt, "==": operator.eq, "!=": operator.ne,
}
UNAVAILABLE = "indisponível"
MAX_MACROS = 12


@dataclass
class Macro:
    source: str = ""
    comparison: str = ">="
    threshold: float = 0
    emoji: str | None = None
    accent: str | None = None
    color: str | None = None
    label_color: str | None = None

    def validate(self, validate_color):
        if not isinstance(self.source, str) or (self.source and not is_numeric(self.source)):
            raise ValueError("Escolha uma leitura numérica para a macro.")
        if not isinstance(self.comparison, str) or self.comparison not in (*COMPARISONS, UNAVAILABLE):
            raise ValueError("Comparação inválida.")
        if type(self.threshold) not in (int, float) or not -1e15 <= self.threshold <= 1e15:
            raise ValueError("O limite precisa ser um número entre −1e15 e 1e15.")
        if self.emoji is not None and (not isinstance(self.emoji, str) or
                                       (self.emoji and self.emoji not in EMOJIS)):
            raise ValueError("Emoji inválido na macro.")
        for value in (self.accent, self.color, self.label_color):
            if value is not None:
                validate_color(value)
        if all(value is None for value in (self.emoji, self.accent, self.color, self.label_color)):
            raise ValueError("Escolha ao menos uma alteração para a macro.")


def apply_macros(item, metrics, gpu_id):
    for rule in item.macros:
        source = rule.source or item.metric
        if not is_numeric(source):
            continue
        value = raw_value(source, metrics, gpu_id)
        available = value is not None and math.isfinite(value)
        if rule.comparison == UNAVAILABLE:
            matches = not available
        else:
            matches = available and COMPARISONS[rule.comparison](value, rule.threshold)
        if matches:
            changes = {name: getattr(rule, name) for name in ("emoji", "accent", "color", "label_color")
                       if getattr(rule, name) is not None}
            return replace(item, **changes)
    return item
