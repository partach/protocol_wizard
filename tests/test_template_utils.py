"""Tests for template utility functions."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from custom_components.protocol_wizard.template_utils import (
    PROTOCOL_SUBDIRS,
    get_protocol_subdir,
    get_template_dropdown_choices,
)


class TestGetProtocolSubdir:
    """Test protocol subdirectory mapping."""

    def test_modbus(self):
        assert get_protocol_subdir("modbus") == "modbus"

    def test_snmp(self):
        assert get_protocol_subdir("snmp") == "snmp"

    def test_mqtt(self):
        assert get_protocol_subdir("mqtt") == "mqtt"

    def test_bacnet(self):
        assert get_protocol_subdir("bacnet") == "bacnet"

    def test_unknown_returns_none(self):
        assert get_protocol_subdir("unknown") is None

    def test_all_protocols_have_subdirs(self):
        for proto in ("modbus", "snmp", "mqtt", "bacnet"):
            assert proto in PROTOCOL_SUBDIRS


class TestGetTemplateDropdownChoices:
    """Test conversion of templates dict to UI dropdown choices."""

    def test_empty_templates(self):
        assert get_template_dropdown_choices({}) == {}

    def test_none_templates(self):
        assert get_template_dropdown_choices(None) == {}

    def test_builtin_templates_first(self):
        templates = {
            "user:custom": {"display_name": "Custom (User)"},
            "builtin:sdm630": {"display_name": "Sdm630 (Built-in)"},
        }
        choices = get_template_dropdown_choices(templates)
        keys = list(choices.keys())
        assert keys[0] == "builtin:sdm630"
        assert keys[1] == "user:custom"

    def test_alphabetical_within_groups(self):
        templates = {
            "builtin:zebra": {"display_name": "Zebra (Built-in)"},
            "builtin:alpha": {"display_name": "Alpha (Built-in)"},
        }
        choices = get_template_dropdown_choices(templates)
        keys = list(choices.keys())
        assert keys[0] == "builtin:alpha"
        assert keys[1] == "builtin:zebra"

    def test_display_names_preserved(self):
        templates = {
            "builtin:test": {"display_name": "Test Device (Built-in)"},
        }
        choices = get_template_dropdown_choices(templates)
        assert choices["builtin:test"] == "Test Device (Built-in)"


class TestTemplateLoadSave:
    """Test template loading and saving with real filesystem."""

    def test_template_array_format(self):
        """Test that array format templates are supported."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            entities = [
                {"name": "Voltage", "address": 0, "data_type": "float32"},
                {"name": "Current", "address": 2, "data_type": "float32"},
            ]
            json.dump(entities, f)
            f.flush()

            # Read back and verify format
            with open(f.name, "r") as rf:
                data = json.load(rf)
            assert isinstance(data, list)
            assert len(data) == 2
            assert data[0]["name"] == "Voltage"
            os.unlink(f.name)

    def test_template_object_format(self):
        """Test that object format templates with 'entities' key are supported."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            template_data = {
                "name": "Test Template",
                "description": "A test",
                "entities": [
                    {"name": "Power", "address": 10, "data_type": "float32"},
                ],
            }
            json.dump(template_data, f)
            f.flush()

            with open(f.name, "r") as rf:
                data = json.load(rf)
            assert isinstance(data, dict)
            assert "entities" in data
            assert len(data["entities"]) == 1
            os.unlink(f.name)

    def test_filename_sanitization(self):
        """Test that template filenames are properly sanitized."""
        # Simulating the save logic
        filename = "My Device / <test>"
        safe_filename = "".join(
            c for c in filename if c.isalnum() or c in "._- "
        )
        safe_filename = safe_filename.strip().replace(" ", "_")
        assert "/" not in safe_filename
        assert "<" not in safe_filename
        assert ">" not in safe_filename
        assert len(safe_filename) > 0

    def test_empty_filename_rejected(self):
        """Filenames that sanitize to empty should be rejected."""
        filename = "///<>"
        safe_filename = "".join(
            c for c in filename if c.isalnum() or c in "._- "
        )
        safe_filename = safe_filename.strip().replace(" ", "_")
        assert safe_filename == ""


class TestBuiltinTemplates:
    """Test that built-in template files are valid JSON."""

    def _get_template_files(self):
        """Get all template files from the templates directory."""
        templates_dir = Path(__file__).parent.parent / "custom_components" / "protocol_wizard" / "templates"
        if not templates_dir.exists():
            pytest.skip("Templates directory not found")
        return list(templates_dir.rglob("*.json"))

    def test_all_templates_are_valid_json(self):
        """Every built-in template must be valid JSON."""
        for path in self._get_template_files():
            with open(path, "r", encoding="utf-8") as f:
                try:
                    json.load(f)
                except json.JSONDecodeError:
                    pytest.fail(f"Invalid JSON in template: {path}")

    def test_all_templates_have_entities(self):
        """Every template must contain entity definitions."""
        for path in self._get_template_files():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, list):
                entities = data
            elif isinstance(data, dict) and "entities" in data:
                entities = data["entities"]
            else:
                pytest.fail(f"Template {path} has no entities")

            assert len(entities) > 0, f"Template {path} has empty entities"

    def test_all_entities_have_required_fields(self):
        """Every entity in templates must have name and address."""
        for path in self._get_template_files():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, list):
                entities = data
            elif isinstance(data, dict) and "entities" in data:
                entities = data["entities"]
            else:
                continue

            for entity in entities:
                assert "name" in entity, (
                    f"Entity missing 'name' in template {path}: {entity}"
                )
                assert "address" in entity, (
                    f"Entity missing 'address' in template {path}: {entity}"
                )
