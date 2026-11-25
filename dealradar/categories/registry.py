"""The only place that knows all category modules. Shared code dispatches through here."""

from __future__ import annotations

from dealradar.categories import apparel, food, home, tech
from dealradar.categories.base import CategoryInfo, CategoryModule
from dealradar.core.enums import Category

_MODULES: dict[Category, CategoryModule] = {
    m.MODULE.info.key: m.MODULE for m in (tech, apparel, food, home)
}


def all_categories() -> tuple[CategoryInfo, ...]:
    return tuple(_MODULES[c].info for c in Category)


def category_info(category: Category) -> CategoryInfo:
    return _MODULES[category].info


def module_for(category: Category) -> CategoryModule:
    return _MODULES[category]
