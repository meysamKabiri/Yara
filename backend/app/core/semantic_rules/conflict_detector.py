from typing import Any


class SemanticRuleConflictError(RuntimeError):
    pass


class ConflictDetectorService:
    def audit(self, rules: dict[str, dict[str, Any]]) -> dict[str, Any]:
        conflicts: list[dict[str, Any]] = []
        semantic_rules = {
            name: rule for name, rule in rules.items() if rule.get("event_type") != "NOTE_EVENT"
        }

        items = list(semantic_rules.items())
        for index, (left_name, left_rule) in enumerate(items):
            for right_name, right_rule in items[index + 1 :]:
                overlap = self._trigger_overlap(left_rule, right_rule)
                if not overlap:
                    continue
                left_id = self._rule_id(left_name, left_rule)
                right_id = self._rule_id(right_name, right_rule)
                conflicts.append(
                    {
                        "type": "OVERLAPPING_RULES",
                        "rules": [left_id, right_id],
                        "description": f"Both rules match {', '.join(repr(item) for item in overlap)} keyword",
                    }
                )
                if left_rule.get("priority") == right_rule.get("priority"):
                    conflicts.append(
                        {
                            "type": "PRIORITY_COLLISION",
                            "rules": [left_id, right_id],
                            "description": "Rules share priority and overlapping triggers",
                        }
                    )

        if not self._has_fallback_coverage(rules):
            conflicts.append(
                {
                    "type": "MISSING_FALLBACK_COVERAGE",
                    "rules": [],
                    "description": "No NOTE_EVENT fallback coverage is defined for unmatched inputs",
                }
            )

        return {"conflicts": conflicts, "severity": self._severity(conflicts)}

    def audit_text(
        self,
        text: str,
        rule_matches: list[dict[str, Any]],
        confidence_gap: float = 0.1,
    ) -> dict[str, Any]:
        if len(rule_matches) < 2:
            return {"conflicts": [], "severity": "NONE"}

        ordered = sorted(rule_matches, key=lambda item: item.get("confidence", 0.0), reverse=True)
        first = ordered[0]
        second = ordered[1]
        first_confidence = float(first.get("confidence", 0.0))
        second_confidence = float(second.get("confidence", 0.0))
        if abs(first_confidence - second_confidence) > confidence_gap:
            return {"conflicts": [], "severity": "NONE"}

        return {
            "conflicts": [
                {
                    "type": "AMBIGUOUS_CLASSIFICATION_ZONE",
                    "rules": [str(first.get("rule_id")), str(second.get("rule_id"))],
                    "description": f"Input {text!r} matches multiple event types with similar confidence",
                }
            ],
            "severity": "HIGH",
        }

    def validate_or_raise(self, rules: dict[str, dict[str, Any]]) -> dict[str, Any]:
        report = self.audit(rules)
        if report["severity"] == "HIGH":
            raise SemanticRuleConflictError("semantic rule conflicts detected")
        return report

    def _trigger_overlap(self, left: dict[str, Any], right: dict[str, Any]) -> list[str]:
        left_keywords = set(left.get("triggers", {}).get("keywords", []))
        right_keywords = set(right.get("triggers", {}).get("keywords", []))
        left_patterns = set(left.get("triggers", {}).get("patterns", []))
        right_patterns = set(right.get("triggers", {}).get("patterns", []))
        return sorted((left_keywords & right_keywords) | (left_patterns & right_patterns))

    def _has_fallback_coverage(self, rules: dict[str, dict[str, Any]]) -> bool:
        note_rule = rules.get("NOTE_EVENT")
        if note_rule is None:
            return False
        return note_rule.get("event_type") == "NOTE_EVENT" and note_rule.get("fallback") is None

    def _rule_id(self, name: str, rule: dict[str, Any]) -> str:
        return str(rule.get("rule_id") or name)

    def _severity(self, conflicts: list[dict[str, Any]]) -> str:
        if any(conflict["type"] in {"PRIORITY_COLLISION", "MISSING_FALLBACK_COVERAGE"} for conflict in conflicts):
            return "HIGH"
        if conflicts:
            return "MEDIUM"
        return "NONE"
