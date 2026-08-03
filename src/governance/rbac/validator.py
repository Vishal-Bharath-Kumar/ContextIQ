"""RBAC (Role-Based Access Control) validation for governance.

Validates user permissions and access levels for retrieved content.
"""
from __future__ import annotations

import logging
from enum import StrEnum

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class UserRole(StrEnum):
    """User roles in the system."""

    ADMIN = "admin"
    DEVELOPER = "developer"
    ANALYST = "analyst"
    VIEWER = "viewer"
    GUEST = "guest"


class Permission(StrEnum):
    """Permission types."""

    READ = "READ"
    WRITE = "WRITE"
    DELETE = "DELETE"
    DEBUG = "DEBUG"
    ADMIN = "ADMIN"
    EXECUTE = "EXECUTE"


class DataClassification(StrEnum):
    """Data classification levels."""

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"
    SECRET = "SECRET"


class RBACValidationResult(BaseModel):
    """Result of RBAC validation."""

    authorized: bool
    user_role: UserRole
    required_permissions: list[Permission]
    granted_permissions: list[Permission]
    denied_permissions: list[Permission] = Field(default_factory=list)
    data_classification: DataClassification = DataClassification.INTERNAL
    message: str = ""


class RBACValidator:
    """Validates RBAC policies for governance checks."""

    # Role to permissions mapping
    ROLE_PERMISSIONS: dict[UserRole, list[Permission]] = {
        UserRole.ADMIN: [
            Permission.READ,
            Permission.WRITE,
            Permission.DELETE,
            Permission.DEBUG,
            Permission.ADMIN,
            Permission.EXECUTE,
        ],
        UserRole.DEVELOPER: [
            Permission.READ,
            Permission.WRITE,
            Permission.DEBUG,
            Permission.EXECUTE,
        ],
        UserRole.ANALYST: [
            Permission.READ,
            Permission.EXECUTE,
        ],
        UserRole.VIEWER: [
            Permission.READ,
        ],
        UserRole.GUEST: [],
    }

    # Data classification access matrix
    # Maps (role, classification) -> allowed
    CLASSIFICATION_ACCESS: dict[tuple[UserRole, DataClassification], bool] = {
        # Admin: full access
        (UserRole.ADMIN, DataClassification.PUBLIC): True,
        (UserRole.ADMIN, DataClassification.INTERNAL): True,
        (UserRole.ADMIN, DataClassification.CONFIDENTIAL): True,
        (UserRole.ADMIN, DataClassification.RESTRICTED): True,
        (UserRole.ADMIN, DataClassification.SECRET): True,
        # Developer: up to CONFIDENTIAL
        (UserRole.DEVELOPER, DataClassification.PUBLIC): True,
        (UserRole.DEVELOPER, DataClassification.INTERNAL): True,
        (UserRole.DEVELOPER, DataClassification.CONFIDENTIAL): True,
        (UserRole.DEVELOPER, DataClassification.RESTRICTED): False,
        (UserRole.DEVELOPER, DataClassification.SECRET): False,
        # Analyst: up to INTERNAL
        (UserRole.ANALYST, DataClassification.PUBLIC): True,
        (UserRole.ANALYST, DataClassification.INTERNAL): True,
        (UserRole.ANALYST, DataClassification.CONFIDENTIAL): False,
        (UserRole.ANALYST, DataClassification.RESTRICTED): False,
        (UserRole.ANALYST, DataClassification.SECRET): False,
        # Viewer: PUBLIC only
        (UserRole.VIEWER, DataClassification.PUBLIC): True,
        (UserRole.VIEWER, DataClassification.INTERNAL): False,
        (UserRole.VIEWER, DataClassification.CONFIDENTIAL): False,
        (UserRole.VIEWER, DataClassification.RESTRICTED): False,
        (UserRole.VIEWER, DataClassification.SECRET): False,
        # Guest: no access
        (UserRole.GUEST, DataClassification.PUBLIC): False,
        (UserRole.GUEST, DataClassification.INTERNAL): False,
        (UserRole.GUEST, DataClassification.CONFIDENTIAL): False,
        (UserRole.GUEST, DataClassification.RESTRICTED): False,
        (UserRole.GUEST, DataClassification.SECRET): False,
    }

    def validate(
        self,
        user_role: UserRole | str,
        required_permissions: list[Permission] | list[str],
        data_classification: DataClassification | str = DataClassification.INTERNAL,
    ) -> RBACValidationResult:
        """Validate user access based on role and required permissions.

        Args:
            user_role: User's role
            required_permissions: List of permissions needed for the operation
            data_classification: Classification level of the data being accessed

        Returns:
            RBACValidationResult with authorization decision
        """
        # Convert string enums if needed
        if isinstance(user_role, str):
            user_role = UserRole(user_role.lower())
        if isinstance(data_classification, str):
            data_classification = DataClassification(data_classification.upper())

        required_perms = [
            Permission(p) if isinstance(p, str) else p
            for p in required_permissions
        ]

        # Get granted permissions for role
        granted_perms = self.ROLE_PERMISSIONS.get(user_role, [])

        # Check permission coverage
        denied_perms = [p for p in required_perms if p not in granted_perms]

        # Check data classification access
        classification_allowed = self.CLASSIFICATION_ACCESS.get(
            (user_role, data_classification), False
        )

        # Determine authorization
        authorized = len(denied_perms) == 0 and classification_allowed

        # Build message
        if not authorized:
            if denied_perms:
                message = f"Missing permissions: {', '.join(p.value for p in denied_perms)}"
            else:
                message = (
                    f"Access denied: {user_role.value} cannot access "
                    f"{data_classification.value} data"
                )
        else:
            message = "Authorization granted"

        return RBACValidationResult(
            authorized=authorized,
            user_role=user_role,
            required_permissions=required_perms,
            granted_permissions=granted_perms,
            denied_permissions=denied_perms,
            data_classification=data_classification,
            message=message,
        )

    def get_max_classification_for_role(self, user_role: UserRole) -> DataClassification:
        """Get the maximum data classification level a role can access."""
        for classification in [
            DataClassification.SECRET,
            DataClassification.RESTRICTED,
            DataClassification.CONFIDENTIAL,
            DataClassification.INTERNAL,
            DataClassification.PUBLIC,
        ]:
            if self.CLASSIFICATION_ACCESS.get((user_role, classification), False):
                return classification
        return DataClassification.PUBLIC
