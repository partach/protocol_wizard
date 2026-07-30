# custom_components/protocol_wizard/template_utils.py
"""Centralized template utilities for Protocol Wizard.

Replaces scattered template handling across config_flow.py, options_flow.py, and __init__.py
with a single, consistent interface supporting both built-in and user templates.
"""
from __future__ import annotations

import logging
import json
#import os
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_PROTOCOL_MODBUS, CONF_PROTOCOL_SNMP , CONF_PROTOCOL_MQTT, CONF_PROTOCOL_BACNET

_LOGGER = logging.getLogger(__name__)

# Template directory structure
BUILTIN_TEMPLATES_SUBDIR = "templates"  # Inside integration
USER_TEMPLATES_DIR = "protocol_wizard/templates"  # In config root

# Protocol subdirectories
PROTOCOL_SUBDIRS = {
    CONF_PROTOCOL_MODBUS: "modbus",
    CONF_PROTOCOL_SNMP: "snmp", 
    CONF_PROTOCOL_MQTT: "mqtt",
    CONF_PROTOCOL_BACNET: "bacnet",
}


def get_protocol_subdir(protocol: str) -> str | None:
    """Get template subdirectory for protocol."""
    return PROTOCOL_SUBDIRS.get(protocol)


def get_builtin_template_dir(hass: HomeAssistant, protocol: str) -> Path | None:
    """Get built-in template directory for protocol."""
    subdir = get_protocol_subdir(protocol)
    if not subdir:
        return None
    
    return Path(hass.config.path(
        "custom_components", DOMAIN, BUILTIN_TEMPLATES_SUBDIR, subdir
    ))


def get_user_template_dir(hass: HomeAssistant, protocol: str) -> Path | None:
    """Get user template directory for protocol."""
    subdir = get_protocol_subdir(protocol)
    if not subdir:
        return None
    
    return Path(hass.config.path(USER_TEMPLATES_DIR, subdir))


def ensure_user_template_dirs(hass: HomeAssistant) -> None:
    """Create user template directories if they don't exist."""
    try:
        base_path = Path(hass.config.path(USER_TEMPLATES_DIR))
        
        for protocol in PROTOCOL_SUBDIRS.keys():
            protocol_dir = base_path / protocol
            protocol_dir.mkdir(parents=True, exist_ok=True)
        
        # Create README
        readme_path = base_path / "README.md"
        if not readme_path.exists():
            readme_path.write_text(_get_readme_content(), encoding='utf-8')
            _LOGGER.info("Created user templates directory: %s", base_path)
    except Exception as err:
        _LOGGER.warning("Failed to create user template directories: %s", err)


def _get_readme_content() -> str:
    """Get README content for user templates directory."""
    return """# Protocol Wizard User Templates

**IMPORTANT: Templates in this directory are SAFE from integration updates!**

When you update Protocol Wizard, templates in `custom_components/protocol_wizard/templates/` 
are DELETED. Templates here are NEVER touched.

https://github.com/partach/protocol_wizard/wiki
"""


async def get_available_templates(
    hass: HomeAssistant, 
    protocol: str
) -> dict[str, dict[str, Any]]:
    """Get all available templates for protocol (built-in + user).
    
    Args:
        hass: Home Assistant instance
        protocol: Protocol name (modbus, snmp, mqtt)
        
    Returns:
        Dict mapping template_id to template info:
        {
            "builtin:devicename": {
                "filename": "devicename.json",
                "display_name": "Device Name (Built-in)",
                "source": "builtin",
                "path": "/path/to/file"
            },
            "user:mydevice": {
                "filename": "mydevice.json",
                "display_name": "My Device (User)",
                "source": "user",
                "path": "/path/to/file"
            }
        }
    """
    templates = {}
    
    # Load built-in templates
    builtin_dir = get_builtin_template_dir(hass, protocol)
    if builtin_dir and await hass.async_add_executor_job(builtin_dir.exists):
        def list_builtin():
            return [
                f.stem for f in builtin_dir.glob("*.json")
                if f.is_file()
            ]
        
        try:
            builtin_templates = await hass.async_add_executor_job(list_builtin)
            for name in builtin_templates:
                template_id = f"builtin:{name}"
                templates[template_id] = {
                    "filename": f"{name}.json",
                    "display_name": f"{name.replace('_', ' ').title()} (Built-in)",
                    "source": "builtin",
                    "path": str(builtin_dir / f"{name}.json"),
                }
        except Exception as err:
            _LOGGER.warning("Failed to list built-in templates for %s: %s", protocol, err)
    
    # Load user templates
    user_dir = get_user_template_dir(hass, protocol)
    if user_dir and await hass.async_add_executor_job(user_dir.exists):
        def list_user():
            return [
                f.stem for f in user_dir.glob("*.json")
                if f.is_file()
            ]
        
        try:
            user_templates = await hass.async_add_executor_job(list_user)
            for name in user_templates:
                template_id = f"user:{name}"
                templates[template_id] = {
                    "filename": f"{name}.json",
                    "display_name": f"{name.replace('_', ' ').title()} (User)",
                    "source": "user",
                    "path": str(user_dir / f"{name}.json"),
                }
        except Exception as err:
            _LOGGER.warning("Failed to list user templates for %s: %s", protocol, err)
    
    return templates


async def load_template(
    hass: HomeAssistant, 
    protocol: str, 
    template_id: str
) -> list[dict] | None:
    """Load template entities from file.
    
    Args:
        hass: Home Assistant instance
        protocol: Protocol name
        template_id: Template ID (e.g., "builtin:devicename" or "user:mydevice")
        
    Returns:
        List of entity dicts or None if failed
    """
    templates = await get_available_templates(hass, protocol)
    template_info = templates.get(template_id)
    
    if not template_info:
        _LOGGER.error("Template not found: %s", template_id)
        return None
    
    template_path = template_info["path"]
    
    def read_template():
        with open(template_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Support both formats:
            # 1. Array of entities (old format)
            # 2. Object with "entities" key (new format)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and "entities" in data:
                return data["entities"]
            else:
                _LOGGER.error("Invalid template format in %s", template_path)
                return None
    
    try:
        entities = await hass.async_add_executor_job(read_template)
        if entities:
            _LOGGER.info("Loaded %d entities from template %s", len(entities), template_id)
        return entities
    except FileNotFoundError:
        _LOGGER.error("Template file not found: %s", template_path)
        return None
    except json.JSONDecodeError as err:
        _LOGGER.error("Failed to parse template %s: %s", template_id, err)
        return None
    except Exception as err:
        _LOGGER.error("Failed to load template %s: %s", template_id, err)
        return None


async def save_template(
    hass: HomeAssistant,
    protocol: str,
    filename: str,
    entities: list[dict],
    metadata: dict[str, Any] | None = None,
    to_user_dir: bool = True
) -> tuple[bool, str]:
    """Save template to file.
    
    Args:
        hass: Home Assistant instance
        protocol: Protocol name
        filename: Filename without .json extension
        entities: List of entity dicts
        metadata: Optional template metadata (name, description, etc.)
        to_user_dir: If True, save to user dir; if False, save to builtin dir
        
    Returns:
        Tuple of (success, message)
    """
    # Sanitize filename
    safe_filename = "".join(c for c in filename if c.isalnum() or c in "._- ")
    safe_filename = safe_filename.strip().replace(" ", "_")
    
    if not safe_filename:
        return False, "Invalid filename"
    
    # Choose directory
    if to_user_dir:
        template_dir = get_user_template_dir(hass, protocol)
        location = "user templates"
    else:
        template_dir = get_builtin_template_dir(hass, protocol)
        location = "built-in templates"
    
    if not template_dir:
        return False, f"Invalid protocol: {protocol}"
    
    # Create directory
    def create_dir():
        template_dir.mkdir(parents=True, exist_ok=True)
    
    await hass.async_add_executor_job(create_dir)
    
    template_path = template_dir / f"{safe_filename}.json"
    
    # Check if exists
    if await hass.async_add_executor_job(template_path.exists):
        return False, f"Template '{safe_filename}' already exists in {location}"
    
    # Build template data
    if metadata:
        # New format with metadata
        template_data = {
            **metadata,
            "entities": entities,
        }
    else:
        # Old format - just entities array
        template_data = entities
    
    # Write file
    def write_file():
        with open(template_path, 'w', encoding='utf-8') as f:
            json.dump(template_data, f, indent=2, ensure_ascii=False)
    
    try:
        await hass.async_add_executor_job(write_file)
        relative_path = template_path.relative_to(Path(hass.config.config_dir))
        _LOGGER.info("Saved template to %s", template_path)
        return True, f"Template saved to {relative_path}"
    except Exception as err:
        _LOGGER.error("Failed to save template: %s", err)
        return False, f"Failed to save: {err}"


async def delete_template(
    hass: HomeAssistant,
    protocol: str,
    template_id: str
) -> tuple[bool, str]:
    """Delete a template (user templates only).
    
    Args:
        hass: Home Assistant instance
        protocol: Protocol name
        template_id: Template ID (must be user template)
        
    Returns:
        Tuple of (success, message)
    """
    # Only allow deleting user templates
    if not template_id.startswith("user:"):
        return False, "Cannot delete built-in templates"
    
    templates = await get_available_templates(hass, protocol)
    template_info = templates.get(template_id)
    
    if not template_info:
        return False, "Template not found"
    
    template_path = Path(template_info["path"])
    
    try:
        await hass.async_add_executor_job(template_path.unlink)
        _LOGGER.info("Deleted template: %s", template_path)
        return True, "Template deleted"
    except Exception as err:
        _LOGGER.error("Failed to delete template: %s", err)
        return False, f"Failed to delete: {err}"


def get_template_dropdown_choices(templates: dict[str, dict]) -> dict[str, str]:
    """Convert templates dict to UI dropdown choices.
    
    Args:
        templates: Dict from get_available_templates()
        
    Returns:
        Dict suitable for vol.In() selector: {template_id: display_name}
    """
    if not templates:
        return {}
    
    choices = {}
    
    # Sort: built-in first, then user, alphabetically within each
    builtin = {k: v for k, v in templates.items() if k.startswith("builtin:")}
    user = {k: v for k, v in templates.items() if k.startswith("user:")}
    
    for template_id, info in sorted(builtin.items()):
        choices[template_id] = info["display_name"]
    
    for template_id, info in sorted(user.items()):
        choices[template_id] = info["display_name"]
    
    return choices


# Legacy compatibility functions
# These allow gradual migration from old code

async def get_available_templates_legacy(
    hass: HomeAssistant,
    protocol: str
) -> list[str]:
    """Get template filenames (legacy format for backward compatibility).
    
    Returns list of filenames without .json extension, from both directories.
    """
    templates = await get_available_templates(hass, protocol)
    return [tid.split(":", 1)[1] for tid in templates.keys()]


async def load_template_legacy(
    hass: HomeAssistant,
    protocol: str,
    filename: str
) -> list[dict] | None:
    """Load template by filename (legacy format).
    
    Tries user directory first, then built-in directory.
    """
    # Try user first
    template_id = f"user:{filename}"
    entities = await load_template(hass, protocol, template_id)
    if entities:
        return entities
    
    # Try built-in
    template_id = f"builtin:{filename}"
    return await load_template(hass, protocol, template_id)
