"""Service for managing model provider credentials in HashiCorp Vault.

Stores and retrieves API keys, base URLs, and other credentials needed
for external model providers (OpenAI, Anthropic, Azure, etc.).
"""
from __future__ import annotations

import os
from typing import Any, Optional

import hvac
from fastapi import HTTPException


class ModelCredentialService:
    """Service for storing and retrieving model credentials from Vault."""
    
    def __init__(self) -> None:
        vault_addr = os.getenv("VAULT_ADDR", "http://vault:8200")
        vault_token = os.getenv("VAULT_TOKEN")
        vault_role_id = os.getenv("VAULT_ROLE_ID")
        vault_secret_id = os.getenv("VAULT_SECRET_ID")
        
        self.client = hvac.Client(url=vault_addr)
        
        # Authenticate with token or AppRole
        if vault_token:
            self.client.token = vault_token
        elif vault_role_id and vault_secret_id:
            self.client.auth.approle.login(
                role_id=vault_role_id,
                secret_id=vault_secret_id,
            )
        else:
            # For local development without Vault
            self.client = None
    
    async def store_credentials(
        self,
        model_id: str,
        provider_type: str,
        credentials: dict[str, Any],
    ) -> bool:
        """Store model credentials in Vault."""
        if self.client is None:
            # Skip Vault storage in local dev
            return False
        
        try:
            path = f"models/{provider_type}/{model_id}"
            
            # Store in Vault KV v2
            self.client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret=credentials,
                mount_point="secret",
            )
            return True
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to store credentials in Vault: {str(e)}"
            )
    
    async def retrieve_credentials(
        self,
        model_id: str,
        provider_type: str,
    ) -> Optional[dict[str, Any]]:
        """Retrieve model credentials from Vault."""
        if self.client is None:
            return None
        
        try:
            path = f"models/{provider_type}/{model_id}"
            
            secret = self.client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point="secret",
            )
            
            return secret["data"]["data"]
        except Exception:
            return None
    
    async def delete_credentials(
        self,
        model_id: str,
        provider_type: str,
    ) -> bool:
        """Delete model credentials from Vault."""
        if self.client is None:
            return False
        
        try:
            path = f"models/{provider_type}/{model_id}"
            
            self.client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=path,
                mount_point="secret",
            )
            return True
        except Exception:
            return False
