"""Loading of the compliance rules."""

from functools import lru_cache
from importlib import resources

import yaml

from complianceops.agents.models import Rule


@lru_cache
def load_rules() -> tuple[Rule, ...]:
    """Return every rule in ``rules.yaml``."""
    text = resources.files("complianceops.agents").joinpath("rules.yaml").read_text("utf-8")
    return tuple(Rule.model_validate(entry) for entry in yaml.safe_load(text))
