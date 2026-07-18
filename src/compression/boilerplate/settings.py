"""Runtime boilerplate rule configuration via environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from src.compression.boilerplate.rules import DEFAULT_RULES, BoilerplateRule


class BoilerplateSettings(BaseSettings):
    """Additional regex rules loaded from environment — semicolon-separated entries.

    Format:
        BOILERPLATE_EXTRA_RULES=<name>|<pattern>;<name>|<pattern>
    Example:
        BOILERPLATE_EXTRA_RULES=internal_header|ACME CORP CONFIDENTIAL

    Disabling rules:
        BOILERPLATE_DISABLED_RULES=maven_build_output,package_lock_metadata
    """

    boilerplate_extra_rules: str = ""
    boilerplate_disabled_rules: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def get_rules(self) -> list[BoilerplateRule]:
        """Return the merged rule list with overrides and extras applied."""
        rules = list(DEFAULT_RULES)
        disabled = {
            r.strip()
            for r in self.boilerplate_disabled_rules.split(",")
            if r.strip()
        }
        rules = [
            r.model_copy(update={"enabled": r.name not in disabled}) for r in rules
        ]
        for entry in self.boilerplate_extra_rules.split(";"):
            if "|" in entry:
                name, pattern = entry.split("|", maxsplit=1)
                rules.append(
                    BoilerplateRule(name=name.strip(), pattern=pattern.strip())
                )
        return rules
