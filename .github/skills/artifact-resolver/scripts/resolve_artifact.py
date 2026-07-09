"""
Project Artifact Resolver

Resolves artifact details (propelFilePath, projectFilePath, templates,
contentType, mcpType, references) by artifact name from project-config.json
in the .propel directory.

Usage:
    python resolve_artifact.py --list
    python resolve_artifact.py --artifact spec
    python resolve_artifact.py --all
    python resolve_artifact.py --config-field basePropelPath
    python resolve_artifact.py --config /custom/path/project-config.json --artifact spec

Notes:
    - resolve_config_field interpolates string values only. Dict and list values
      are returned as-is; string interpolation is not applied recursively to
      nested structures.
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Default config: <project-root>/.propel/project-config.json
DEFAULT_CONFIG = Path.cwd() / ".propel" / "project-config.json"


def load_config(config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        print(json.dumps({"error": f"Config file not found: {config_path}"}))
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def interpolate(value: str, config: dict) -> str:
    """Replace ${key} placeholders with top-level config values and normalise slashes."""
    def replacer(match):
        key = match.group(1)
        if key not in config:
            raise ValueError(f"Unresolved variable: ${{{key}}}")
        return str(config[key])
    result = re.sub(r"\$\{(\w+)\}", replacer, value)
    # Normalise double slashes (but preserve protocol prefixes like http://)
    result = re.sub(r"(?<!:)//+", "/", result)
    return result


def list_artifacts(config: dict) -> None:
    artifacts = config.get("artifacts", {})
    if not artifacts:
        print(json.dumps({"error": "No artifacts defined in project config"}))
        sys.exit(1)
    result = {
        "projectName": config.get("projectName", ""),
        "availableArtifacts": list(artifacts.keys()),
    }
    print(json.dumps(result, indent=2))


def normalize_path(path: str) -> str:
    """Normalise double slashes (but preserve protocol prefixes like http://)."""
    return re.sub(r"(?<!:)//+", "/", path)


UML_SUBDIR = "uml-models"


def build_uml_paths(propel_dir: str, project_dir: str) -> tuple:
    """Derive propelUmlPath and projectUmlPath by appending the fixed UML
    subdirectory to the artifact's propel and project directory paths."""
    propel_uml = normalize_path(propel_dir + "/" + UML_SUBDIR)
    project_uml = normalize_path(project_dir + "/" + UML_SUBDIR)
    return propel_uml, project_uml


def resolve_artifact(config: dict, artifact_key: str) -> None:
    artifacts = config.get("artifacts", {})
    if artifact_key not in artifacts:
        result = {
            "error": f"Artifact '{artifact_key}' not found",
            "availableArtifacts": list(artifacts.keys()),
        }
        print(json.dumps(result, indent=2))
        sys.exit(1)
    entry = artifacts[artifact_key]
    propel_dir = interpolate(entry.get("propelDirPath", ""), config)
    project_dir = interpolate(entry.get("projectDirPath", ""), config)
    propel_file = normalize_path(propel_dir + "/" + entry.get("propelFileName", ""))
    project_file = normalize_path(project_dir + "/" + entry.get("projectFileName", ""))
    propel_uml, project_uml = build_uml_paths(propel_dir, project_dir)
    result = {
        "artifact": artifact_key,
        "propelFileName": entry.get("propelFileName", ""),
        "propelFileNames": entry.get("propelFileNames", {}),
        "propelDirPath": propel_dir,
        "propelFilePath": propel_file,
        "projectFilePath": project_file,
        "propelUmlPath": propel_uml,
        "projectUmlPath": project_uml,
        "templates": entry.get("templates", {}),
        "schema": entry.get("schema", ""),
        "contentType": entry.get("contentType", ""),
        "mcpType": entry.get("mcpType", ""),
        "references": entry.get("references", []),
        "workflow": entry.get("workflow", ""),
    }
    print(json.dumps(result, indent=2))


def resolve_config_field(config: dict, field_name: str) -> None:
    if field_name not in config:
        result = {
            "error": f"Config field '{field_name}' not found",
            "availableFields": [
                k for k in config.keys() if k != "artifacts"
            ],
        }
        print(json.dumps(result, indent=2))
        sys.exit(1)
    value = config[field_name]
    if isinstance(value, str):
        value = interpolate(value, config)
    # Note: dict and list values are returned as-is without recursive interpolation.
    result = {
        "field": field_name,
        "value": value,
    }
    print(json.dumps(result, indent=2))


def resolve_all(config: dict) -> None:
    artifacts = config.get("artifacts", {})
    if not artifacts:
        print(json.dumps({"error": "No artifacts defined in project config"}))
        sys.exit(1)
    resolved = {}
    for key, entry in artifacts.items():
        propel_dir = interpolate(entry.get("propelDirPath", ""), config)
        project_dir = interpolate(entry.get("projectDirPath", ""), config)
        propel_file = normalize_path(propel_dir + "/" + entry.get("propelFileName", ""))
        project_file = normalize_path(project_dir + "/" + entry.get("projectFileName", ""))
        propel_uml, project_uml = build_uml_paths(propel_dir, project_dir)
        resolved[key] = {
            "propelFileName": entry.get("propelFileName", ""),
            "propelFileNames": entry.get("propelFileNames", {}),
            "propelDirPath": propel_dir,
            "propelFilePath": propel_file,
            "projectFilePath": project_file,
            "propelUmlPath": propel_uml,
            "projectUmlPath": project_uml,
            "templates": entry.get("templates", {}),
            "schema": entry.get("schema", ""),
            "contentType": entry.get("contentType", ""),
            "mcpType": entry.get("mcpType", ""),
            "references": entry.get("references", []),
            "workflow": entry.get("workflow", ""),
        }
    result = {
        "projectName": config.get("projectName", ""),
        "description": config.get("description", ""),
        "artifacts": resolved,
    }
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Resolve project artifact details")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to project-config.json (defaults to .propel/project-config.json in project root)",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="List all artifact keys")
    group.add_argument("--artifact", type=str, help="Resolve a specific artifact by key")
    group.add_argument("--all", action="store_true", help="Resolve all artifacts")
    group.add_argument("--config-field", type=str, help="Resolve a top-level config field by name")

    args = parser.parse_args()
    config = load_config(args.config)

    try:
        if args.list:
            list_artifacts(config)
        elif args.artifact:
            resolve_artifact(config, args.artifact)
        elif args.all:
            resolve_all(config)
        elif args.config_field:
            resolve_config_field(config, args.config_field)
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
