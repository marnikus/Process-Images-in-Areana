from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class SelectorObject:
    name: str
    primary: str
    fallbacks: List[str] = field(default_factory=list)
    scope: Optional[str] = None  # parent selector to scope within
    mustBeVisible: bool = True
    mustBeEnabled: bool = False
    expectedCount: int = 1
    textCondition: Optional[str] = None  # exact or contains text
    textConditionType: str = "equals"  # equals, contains, regex
    verification: Optional[str] = None
    evidence: Optional[str] = None
    lastVerified: Optional[str] = None
    tier: str = ""  # RULE 21: semantic | structural | class-fragment

    def all_selectors(self) -> List[str]:
        return [self.primary] + self.fallbacks

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "primary": self.primary,
            "fallbacks": self.fallbacks,
            "scope": self.scope,
            "mustBeVisible": self.mustBeVisible,
            "mustBeEnabled": self.mustBeEnabled,
            "expectedCount": self.expectedCount,
            "textCondition": self.textCondition,
            "textConditionType": self.textConditionType,
            "verification": self.verification,
            "evidence": self.evidence,
            "lastVerified": self.lastVerified,
            "tier": self.tier,
        }
