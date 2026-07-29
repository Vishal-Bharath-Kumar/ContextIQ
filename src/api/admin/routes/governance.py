"""Governance settings API routes for admin portal.

Provides endpoints to manage comprehensive governance policies including:
- Compliance standards (GDPR, SOC2, HIPAA, PCI-DSS, CCPA)
- RBAC role permissions and data classification
- Pattern detection configuration
- Risk scoring weights and thresholds
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.admin.dependencies import require_admin_role
from src.data.dependencies import get_db
from src.data.models.governance_settings import GovernanceSettingsRecord
from src.gateway.schemas.auth_types import JWTClaims

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/governance", tags=["Admin — Governance"])

AdminClaims = Annotated[JWTClaims, Depends(require_admin_role)]
_DEFAULT_SETTINGS_KEY = "default"


def _actor_identity(claims: JWTClaims) -> str:
    return claims.email or claims.preferred_username or claims.sub


# ------------------------------------------------------------------ #
# Request/Response Models                                             #
# ------------------------------------------------------------------ #


class ComplianceStandard(BaseModel):
    """Compliance standard configuration."""

    id: str
    name: str
    description: str
    enabled: bool
    requirement_count: int = Field(alias="requirementCount")

    class Config:
        populate_by_name = True


class ComplianceSettings(BaseModel):
    """Compliance settings configuration."""

    standards: list[ComplianceStandard]


class RolePermissions(BaseModel):
    """RBAC role permissions configuration."""

    role: str
    display_name: str = Field(alias="displayName")
    permissions: list[str]
    max_classification: str = Field(alias="maxClassification")
    color: str

    class Config:
        populate_by_name = True


class RBACSettings(BaseModel):
    """RBAC settings configuration."""

    roles: list[RolePermissions]


class PatternConfig(BaseModel):
    """Pattern detection configuration."""

    id: str
    name: str
    severity: str
    enabled: bool
    match_count: int | None = Field(None, alias="matchCount")

    class Config:
        populate_by_name = True


class PatternCategory(BaseModel):
    """Pattern category configuration."""

    id: str
    name: str
    description: str
    patterns: list[PatternConfig]


class PatternDetectionSettings(BaseModel):
    """Pattern detection settings configuration."""

    categories: list[PatternCategory]


class SeverityWeight(BaseModel):
    """Severity weight configuration."""

    severity: str
    weight: float
    description: str


class RiskScoringSettings(BaseModel):
    """Risk scoring settings configuration."""

    severity_weights: list[SeverityWeight] = Field(alias="severityWeights")
    violation_penalty: float = Field(alias="violationPenalty")

    class Config:
        populate_by_name = True


class GovernanceSettings(BaseModel):
    """Complete governance settings."""

    compliance: ComplianceSettings
    rbac: RBACSettings
    patterns: PatternDetectionSettings
    risk_scoring: RiskScoringSettings = Field(alias="riskScoring")

    class Config:
        populate_by_name = True


# ------------------------------------------------------------------ #
# Default Settings (seeded into DB on first access)                  #
# ------------------------------------------------------------------ #


DEFAULT_COMPLIANCE_SETTINGS = ComplianceSettings(
    standards=[
        ComplianceStandard(
            id="GDPR",
            name="GDPR",
            description="EU General Data Protection Regulation - Personal data protection",
            enabled=True,
            requirementCount=5,
        ),
        ComplianceStandard(
            id="SOC2",
            name="SOC2",
            description="System and Organization Controls 2 - Security and access control",
            enabled=True,
            requirementCount=7,
        ),
        ComplianceStandard(
            id="HIPAA",
            name="HIPAA",
            description="Health Insurance Portability and Accountability Act - PHI protection",
            enabled=False,
            requirementCount=4,
        ),
        ComplianceStandard(
            id="PCI_DSS",
            name="PCI-DSS",
            description="Payment Card Industry Data Security Standard - Payment data security",
            enabled=True,
            requirementCount=6,
        ),
        ComplianceStandard(
            id="CCPA",
            name="CCPA",
            description="California Consumer Privacy Act - Personal information protection",
            enabled=False,
            requirementCount=4,
        ),
    ]
)

DEFAULT_RBAC_SETTINGS = RBACSettings(
    roles=[
        RolePermissions(
            role="admin",
            displayName="Admin",
            permissions=["READ", "WRITE", "DELETE", "DEBUG", "ADMIN", "EXECUTE"],
            maxClassification="SECRET",
            color="purple",
        ),
        RolePermissions(
            role="developer",
            displayName="Developer",
            permissions=["READ", "WRITE", "DEBUG", "EXECUTE"],
            maxClassification="CONFIDENTIAL",
            color="blue",
        ),
        RolePermissions(
            role="analyst",
            displayName="Analyst",
            permissions=["READ", "EXECUTE"],
            maxClassification="INTERNAL",
            color="green",
        ),
        RolePermissions(
            role="viewer",
            displayName="Viewer",
            permissions=["READ"],
            maxClassification="PUBLIC",
            color="gray",
        ),
        RolePermissions(
            role="guest",
            displayName="Guest",
            permissions=[],
            maxClassification="NONE",
            color="slate",
        ),
    ]
)

DEFAULT_PATTERN_SETTINGS = PatternDetectionSettings(
    categories=[
        PatternCategory(
            id="cloud",
            name="Cloud Provider Secrets",
            description="AWS, GCP, Azure credentials and access keys",
            patterns=[
                PatternConfig(
                    id="AWS_ACCESS_KEY_ID",
                    name="AWS Access Key ID",
                    severity="CRITICAL",
                    enabled=True,
                    matchCount=247,
                ),
                PatternConfig(
                    id="AWS_SECRET_ACCESS_KEY",
                    name="AWS Secret Access Key",
                    severity="CRITICAL",
                    enabled=True,
                    matchCount=189,
                ),
                PatternConfig(
                    id="GCP_API_KEY",
                    name="GCP API Key",
                    severity="CRITICAL",
                    enabled=True,
                    matchCount=94,
                ),
                PatternConfig(
                    id="GCP_SERVICE_ACCOUNT",
                    name="GCP Service Account",
                    severity="CRITICAL",
                    enabled=True,
                    matchCount=31,
                ),
                PatternConfig(
                    id="AZURE_CONNECTION_STRING",
                    name="Azure Connection String",
                    severity="CRITICAL",
                    enabled=True,
                    matchCount=67,
                ),
            ],
        ),
        PatternCategory(
            id="scm",
            name="Source Control Tokens",
            description="GitHub, GitLab, Bitbucket access tokens",
            patterns=[
                PatternConfig(
                    id="GITHUB_PAT",
                    name="GitHub Personal Access Token",
                    severity="CRITICAL",
                    enabled=True,
                    matchCount=423,
                ),
                PatternConfig(
                    id="GITLAB_PAT",
                    name="GitLab Personal Access Token",
                    severity="CRITICAL",
                    enabled=True,
                    matchCount=156,
                ),
                PatternConfig(
                    id="BITBUCKET_TOKEN",
                    name="Bitbucket Token",
                    severity="CRITICAL",
                    enabled=True,
                    matchCount=78,
                ),
            ],
        ),
        PatternCategory(
            id="ai_llm",
            name="AI/LLM API Keys",
            description="OpenAI, Anthropic, Google AI, HuggingFace tokens",
            patterns=[
                PatternConfig(
                    id="OPENAI_API_KEY",
                    name="OpenAI API Key",
                    severity="CRITICAL",
                    enabled=True,
                    matchCount=312,
                ),
                PatternConfig(
                    id="ANTHROPIC_API_KEY",
                    name="Anthropic API Key",
                    severity="CRITICAL",
                    enabled=True,
                    matchCount=145,
                ),
                PatternConfig(
                    id="GOOGLE_AI_API_KEY",
                    name="Google AI API Key",
                    severity="CRITICAL",
                    enabled=True,
                    matchCount=89,
                ),
                PatternConfig(
                    id="HUGGINGFACE_TOKEN",
                    name="HuggingFace Token",
                    severity="CRITICAL",
                    enabled=True,
                    matchCount=67,
                ),
            ],
        ),
        PatternCategory(
            id="generic",
            name="Generic Secrets",
            description="API keys, passwords, tokens, JWT, private keys",
            patterns=[
                PatternConfig(
                    id="GENERIC_API_KEY",
                    name="Generic API Key",
                    severity="HIGH",
                    enabled=True,
                    matchCount=856,
                ),
                PatternConfig(
                    id="GENERIC_SECRET",
                    name="Generic Secret/Password",
                    severity="HIGH",
                    enabled=True,
                    matchCount=634,
                ),
                PatternConfig(
                    id="BEARER_TOKEN",
                    name="Bearer Token",
                    severity="HIGH",
                    enabled=True,
                    matchCount=421,
                ),
                PatternConfig(
                    id="JWT_TOKEN",
                    name="JWT Token",
                    severity="HIGH",
                    enabled=True,
                    matchCount=789,
                ),
                PatternConfig(
                    id="PRIVATE_KEY",
                    name="Private Key (RSA/SSH)",
                    severity="CRITICAL",
                    enabled=True,
                    matchCount=123,
                ),
                PatternConfig(
                    id="PASSWORD_IN_URL",
                    name="Password in URL",
                    severity="CRITICAL",
                    enabled=True,
                    matchCount=234,
                ),
            ],
        ),
        PatternCategory(
            id="database",
            name="Database Credentials",
            description="PostgreSQL, MongoDB, MySQL connection strings",
            patterns=[
                PatternConfig(
                    id="DATABASE_URL",
                    name="Database Connection URL",
                    severity="CRITICAL",
                    enabled=True,
                    matchCount=345,
                ),
                PatternConfig(
                    id="POSTGRES_CONNECTION",
                    name="PostgreSQL Connection",
                    severity="CRITICAL",
                    enabled=True,
                    matchCount=267,
                ),
                PatternConfig(
                    id="MONGODB_CONNECTION",
                    name="MongoDB Connection",
                    severity="CRITICAL",
                    enabled=True,
                    matchCount=178,
                ),
            ],
        ),
        PatternCategory(
            id="pii",
            name="Personally Identifiable Information",
            description="Email, phone, SSN, credit cards, IP addresses",
            patterns=[
                PatternConfig(
                    id="EMAIL_ADDRESS",
                    name="Email Address",
                    severity="HIGH",
                    enabled=True,
                    matchCount=2341,
                ),
                PatternConfig(
                    id="PHONE_NUMBER",
                    name="Phone Number",
                    severity="MEDIUM",
                    enabled=True,
                    matchCount=1567,
                ),
                PatternConfig(
                    id="US_SSN",
                    name="US Social Security Number",
                    severity="HIGH",
                    enabled=True,
                    matchCount=89,
                ),
                PatternConfig(
                    id="UK_NI_NUMBER",
                    name="UK National Insurance",
                    severity="HIGH",
                    enabled=True,
                    matchCount=45,
                ),
                PatternConfig(
                    id="CREDIT_CARD_NUMBER",
                    name="Credit Card Number",
                    severity="HIGH",
                    enabled=True,
                    matchCount=234,
                ),
                PatternConfig(
                    id="IP_ADDRESS",
                    name="IP Address",
                    severity="LOW",
                    enabled=False,
                    matchCount=5678,
                ),
            ],
        ),
        PatternCategory(
            id="infrastructure",
            name="Infrastructure & Communication",
            description="Vault tokens, Slack webhooks",
            patterns=[
                PatternConfig(
                    id="VAULT_TOKEN",
                    name="HashiCorp Vault Token",
                    severity="CRITICAL",
                    enabled=True,
                    matchCount=156,
                ),
                PatternConfig(
                    id="SLACK_TOKEN",
                    name="Slack Token",
                    severity="CRITICAL",
                    enabled=True,
                    matchCount=234,
                ),
                PatternConfig(
                    id="SLACK_WEBHOOK",
                    name="Slack Webhook URL",
                    severity="HIGH",
                    enabled=True,
                    matchCount=189,
                ),
            ],
        ),
    ]
)

DEFAULT_RISK_SCORING_SETTINGS = RiskScoringSettings(
    severityWeights=[
        SeverityWeight(severity="INFO", weight=0.1, description="Informational findings"),
        SeverityWeight(severity="LOW", weight=0.5, description="Low-risk patterns (IP addresses)"),
        SeverityWeight(severity="MEDIUM", weight=1.5, description="Medium-risk PII"),
        SeverityWeight(severity="HIGH", weight=3.0, description="High-risk PII (SSN, credit cards)"),
        SeverityWeight(severity="CRITICAL", weight=5.0, description="Critical secrets (API keys, passwords)"),
    ],
    violationPenalty=0.5,
)


def _default_settings_payload() -> dict[str, dict]:
    return {
        "compliance": DEFAULT_COMPLIANCE_SETTINGS.model_dump(by_alias=True),
        "rbac": DEFAULT_RBAC_SETTINGS.model_dump(by_alias=True),
        "patterns": DEFAULT_PATTERN_SETTINGS.model_dump(by_alias=True),
        "risk_scoring": DEFAULT_RISK_SCORING_SETTINGS.model_dump(by_alias=True),
    }


def _record_to_settings(record: GovernanceSettingsRecord) -> GovernanceSettings:
    return GovernanceSettings(
        compliance=record.compliance,
        rbac=record.rbac,
        patterns=record.patterns,
        riskScoring=record.risk_scoring,
    )


async def _get_or_create_settings_record(session: AsyncSession) -> GovernanceSettingsRecord:
    record = (
        await session.execute(
            select(GovernanceSettingsRecord).where(
                GovernanceSettingsRecord.settings_key == _DEFAULT_SETTINGS_KEY
            )
        )
    ).scalar_one_or_none()

    if record is not None:
        return record

    payload = _default_settings_payload()
    record = GovernanceSettingsRecord(
        settings_key=_DEFAULT_SETTINGS_KEY,
        compliance=payload["compliance"],
        rbac=payload["rbac"],
        patterns=payload["patterns"],
        risk_scoring=payload["risk_scoring"],
    )
    session.add(record)
    try:
        await session.commit()
        await session.refresh(record)
        return record
    except IntegrityError:
        await session.rollback()
        existing_record = (
            await session.execute(
                select(GovernanceSettingsRecord).where(
                    GovernanceSettingsRecord.settings_key == _DEFAULT_SETTINGS_KEY
                )
            )
        ).scalar_one_or_none()
        if existing_record is None:
            raise
        return existing_record


# ------------------------------------------------------------------ #
# Route Handlers                                                      #
# ------------------------------------------------------------------ #


@router.get("/settings", response_model=GovernanceSettings)
async def get_governance_settings(
    claims: AdminClaims,
    session: AsyncSession = Depends(get_db),
) -> GovernanceSettings:
    """Get complete governance settings.

    Returns all governance configuration including compliance standards,
    RBAC permissions, pattern detection, and risk scoring settings.
    """
    record = await _get_or_create_settings_record(session)
    return _record_to_settings(record)


@router.put("/compliance", response_model=ComplianceSettings)
async def update_compliance_settings(
    settings: ComplianceSettings,
    claims: AdminClaims,
    session: AsyncSession = Depends(get_db),
) -> ComplianceSettings:
    """Update compliance standards configuration.

    Enable or disable compliance standards (GDPR, SOC2, HIPAA, PCI-DSS, CCPA).
    """
    try:
        actor = _actor_identity(claims)
        record = await _get_or_create_settings_record(session)
        record.compliance = settings.model_dump(by_alias=True)
        await session.commit()
        logger.info(
            f"Compliance settings updated by {actor}: "
            f"enabled={[s.id for s in settings.standards if s.enabled]}"
        )
        return settings
    except Exception as exc:
        await session.rollback()
        logger.exception("Failed to update compliance settings")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist compliance settings.",
        ) from exc


@router.put("/rbac", response_model=RBACSettings)
async def update_rbac_settings(
    settings: RBACSettings,
    claims: AdminClaims,
    session: AsyncSession = Depends(get_db),
) -> RBACSettings:
    """Update RBAC role permissions and data classification settings.

    Configure permissions and data access levels for each user role.
    """
    try:
        actor = _actor_identity(claims)
        record = await _get_or_create_settings_record(session)
        record.rbac = settings.model_dump(by_alias=True)
        await session.commit()
        logger.info(
            f"RBAC settings updated by {actor}: "
            f"roles={[r.role for r in settings.roles]}"
        )
        return settings
    except Exception as exc:
        await session.rollback()
        logger.exception("Failed to update RBAC settings")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist RBAC settings.",
        ) from exc


@router.put("/patterns", response_model=PatternDetectionSettings)
async def update_pattern_settings(
    settings: PatternDetectionSettings,
    claims: AdminClaims,
    session: AsyncSession = Depends(get_db),
) -> PatternDetectionSettings:
    """Update pattern detection configuration.

    Enable or disable specific secret and PII detection patterns.
    """
    try:
        actor = _actor_identity(claims)
        record = await _get_or_create_settings_record(session)
        record.patterns = settings.model_dump(by_alias=True)
        await session.commit()
        total_enabled = sum(
            sum(1 for p in cat.patterns if p.enabled)
            for cat in settings.categories
        )
        logger.info(
            f"Pattern settings updated by {actor}: "
            f"enabled_patterns={total_enabled}"
        )
        return settings
    except Exception as exc:
        await session.rollback()
        logger.exception("Failed to update pattern settings")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist pattern settings.",
        ) from exc


@router.put("/risk-scoring", response_model=RiskScoringSettings)
async def update_risk_scoring_settings(
    settings: RiskScoringSettings,
    claims: AdminClaims,
    session: AsyncSession = Depends(get_db),
) -> RiskScoringSettings:
    """Update risk scoring weights and thresholds.

    Configure severity weights and compliance violation penalties.
    """
    try:
        actor = _actor_identity(claims)
        record = await _get_or_create_settings_record(session)
        record.risk_scoring = settings.model_dump(by_alias=True)
        await session.commit()
        logger.info(
            f"Risk scoring settings updated by {actor}: "
            f"violation_penalty={settings.violation_penalty}"
        )
        return settings
    except Exception as exc:
        await session.rollback()
        logger.exception("Failed to update risk scoring settings")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist risk scoring settings.",
        ) from exc
