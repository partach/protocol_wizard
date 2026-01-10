#------------------------------------------
# options_flow.py – Protocol Wizard (protocol-agnostic)
#------------------------------------------
"""Options flow for Protocol Wizard – fully protocol-agnostic."""
from __future__ import annotations

import logging
import json
import os
from datetime import timedelta
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_UPDATE_INTERVAL,
    CONF_ENTITIES,
    CONF_REGISTERS,
    CONF_PROTOCOL,
    CONF_PROTOCOL_MODBUS,
    CONF_PROTOCOL_SNMP,
    CONF_BYTE_ORDER,
    CONF_WORD_ORDER,
    CONF_REGISTER_TYPE,
)

_LOGGER = logging.getLogger(__name__)


# ============================================================================
# Options Flow
# ============================================================================

class ProtocolWizardOptionsFlow(config_entries.OptionsFlow):
    """Protocol-agnostic options flow for Protocol Wizard."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        self._config_entry = config_entry
        self.protocol = config_entry.data.get(CONF_PROTOCOL, CONF_PROTOCOL_MODBUS)

        self.schema_handler = self._get_schema_handler()

        # Determine the correct config key based on protocol
        if self.protocol == CONF_PROTOCOL_MODBUS:
            config_key = CONF_REGISTERS
        else:
            config_key = CONF_ENTITIES  # Future-proof for other protocols
            
        self._entities: list[dict] = list(config_entry.options.get(config_key, []))
        self._edit_index: int | None = None

    @property
    def config_entry(self) -> config_entries.ConfigEntry:
        return self._config_entry

    # ------------------------------------------------------------------
    # INIT
    # ------------------------------------------------------------------

    async def async_step_init(self, user_input=None):
        menu_options = {
            "settings": "Settings",
            "add_entity": "Add entity",
            "load_template": "Load template",
        }
        if self._entities:
            menu_options["list_entities"] = f"Entities ({len(self._entities)})"
            menu_options["edit_entity"] = "Edit entity"

        return self.async_show_menu(step_id="init", menu_options=menu_options)

    # ------------------------------------------------------------------
    # SETTINGS
    # ------------------------------------------------------------------

    async def async_step_settings(self, user_input=None):
        if user_input:
            interval = user_input[CONF_UPDATE_INTERVAL]

            coordinator = (
                self.hass.data
                .get(DOMAIN, {})
                .get("coordinators", {})
                .get(self._config_entry.entry_id)
            )
            if coordinator:
                coordinator.update_interval = timedelta(seconds=interval)

            self._save_options({CONF_UPDATE_INTERVAL: interval})
            return self.async_abort(reason="settings_updated")

        current = self._config_entry.options.get(CONF_UPDATE_INTERVAL, 10)
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema({
                vol.Required(CONF_UPDATE_INTERVAL, default=current): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=300)
                )
            }),
        )

    # ------------------------------------------------------------------
    # ADD
    # ------------------------------------------------------------------

    async def async_step_add_entity(self, user_input=None):
        errors = {}

        if user_input:
            processed = self.schema_handler.process_input(user_input, errors, existing=None)
            if processed and not errors:
                self._entities.append(processed)
                self._save_entities()
                return await self.async_step_init()

        return self.async_show_form(
            step_id="add_entity",
            data_schema=self.schema_handler.get_schema(),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # EDIT SELECT
    # ------------------------------------------------------------------

    async def async_step_edit_entity(self, user_input=None):
        if user_input:
            self._edit_index = int(user_input["entity"])
            return await self.async_step_edit_entity_form()

        options = [
            selector.SelectOptionDict(
                value=str(i),
                label=self.schema_handler.format_label(e),
            )
            for i, e in enumerate(self._entities)
        ]

        return self.async_show_form(
            step_id="edit_entity",
            data_schema=vol.Schema({
                vol.Required("entity"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }),
        )

    # ------------------------------------------------------------------
    # EDIT FORM
    # ------------------------------------------------------------------

    async def async_step_edit_entity_form(self, user_input=None):
        entity = self._entities[self._edit_index]
        errors = {}

        if user_input:
            processed = self.schema_handler.process_input(user_input, errors, existing=entity)
            if processed and not errors:
                self._entities[self._edit_index] = processed
                self._save_entities()
                return await self.async_step_init()

        defaults = self.schema_handler.get_defaults(entity)
        return self.async_show_form(
            step_id="edit_entity_form",
            data_schema=self.schema_handler.get_schema(defaults),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # LIST / DELETE
    # ------------------------------------------------------------------

    async def async_step_list_entities(self, user_input=None):
        if user_input:
            delete = set(user_input.get("delete", []))
            self._entities = [
                e for i, e in enumerate(self._entities)
                if str(i) not in delete
            ]
            self._save_entities()
            return await self.async_step_init()

        options = [
            selector.SelectOptionDict(
                value=str(i),
                label=self.schema_handler.format_label(e),
            )
            for i, e in enumerate(self._entities)
        ]

        return self.async_show_form(
            step_id="list_entities",
            data_schema=vol.Schema({
                vol.Optional("delete"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }),
        )

    # ------------------------------------------------------------------
    # TEMPLATE
    # ------------------------------------------------------------------

    async def async_step_load_template(self, user_input=None):
        """Load a device template — protocol-specific folder."""
        if user_input:
            filename = user_input["template"]
            # Protocol-specific template directory
            protocol_subdir = "modbus" if self.protocol == CONF_PROTOCOL_MODBUS else "snmp"
            template_dir = self.hass.config.path(
                "custom_components", DOMAIN, "templates", protocol_subdir
            )
            path = os.path.join(template_dir, f"{filename}.json")

            try:
                data = await self.hass.async_add_executor_job(self._load_template, path)
                added = self.schema_handler.merge_template(self._entities, data)
                if not added:
                    return self.async_show_form(
                        step_id="load_template",
                        data_schema=self._get_template_schema(),
                        errors={"base": "template_empty_or_duplicate"},
                    )
                self._save_entities()
                return await self.async_step_init()
            except FileNotFoundError:
                _LOGGER.error("Template file not found: %s", path)
                return self.async_show_form(
                    step_id="load_template",
                    data_schema=self._get_template_schema(),
                    errors={"base": "template_not_found"},
                )
            except Exception as err:
                _LOGGER.error("Template load failed: %s", err)
                return self.async_show_form(
                    step_id="load_template",
                    data_schema=self._get_template_schema(),
                    errors={"base": "load_failed"},
                )

        # List templates from protocol-specific folder
        protocol_subdir = "modbus" if self.protocol == CONF_PROTOCOL_MODBUS else "snmp"
        template_dir = self.hass.config.path(
            "custom_components", DOMAIN, "templates", protocol_subdir
        )

        try:
            files = await self.hass.async_add_executor_job(
                lambda: [
                    f[:-5]  # strip .json
                    for f in os.listdir(template_dir)
                    if f.endswith(".json")
                ] if os.path.exists(template_dir) else []
            )
            templates = sorted(files)
        except Exception as err:
            _LOGGER.debug("Failed to list templates in %s: %s", template_dir, err)
            templates = []

        if not templates:
            return self.async_abort(reason="no_templates")

        return self.async_show_form(
            step_id="load_template",
            data_schema=vol.Schema({
                vol.Required("template"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[selector.SelectOptionDict(value=t, label=t) for t in templates],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }),
            description_placeholders={"templates": ", ".join(templates)},
        )
    # ------------------------------------------------------------------
    # INTERNAL
    # ------------------------------------------------------------------
    def _get_template_schema(self, templates=None):
        """Return schema for template selection."""
        if templates is None:
            templates = []
        return vol.Schema({
            vol.Required("template"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[selector.SelectOptionDict(value=t, label=t) for t in templates],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        })
        
    @staticmethod
    def _load_template(path: str):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_entities(self):
        options = dict(self._config_entry.options)
        config_key = CONF_REGISTERS if self.protocol == CONF_PROTOCOL_MODBUS else CONF_ENTITIES
        options[config_key] = self._entities
        self.hass.config_entries.async_update_entry(self._config_entry, options=options)
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(self._config_entry.entry_id)
        )

    def _save_options(self, updates: dict):
        options = dict(self._config_entry.options)
        options.update(updates)
        self.hass.config_entries.async_update_entry(self._config_entry, options=options)

    def _get_schema_handler(self):
        if self.protocol == CONF_PROTOCOL_SNMP:
            return SNMPSchemaHandler()
        return ModbusSchemaHandler()


# ============================================================================
# SCHEMA HANDLERS
# ============================================================================

class ModbusSchemaHandler:
    """Handles Modbus-specific schema and input processing."""

    @staticmethod
    def get_schema(defaults: dict | None = None) -> vol.Schema:
        defaults = defaults or {}

        schema = {
            vol.Required("name", default=defaults.get("name")): str,

            vol.Required("address", default=defaults.get("address")):
                vol.All(vol.Coerce(int), vol.Range(min=0, max=65535)),
            
            vol.Required(
                CONF_REGISTER_TYPE,
                default=defaults.get(CONF_REGISTER_TYPE, "input")
            ):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["auto", "holding", "input", "coil", "discrete"],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            vol.Required("data_type", default=defaults.get("data_type", "uint16")):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            "uint16", "int16",
                            "uint32", "int32",
                            "float32",
                            "uint64", "int64",
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),

            vol.Required("rw", default=defaults.get("rw", "read")):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["read", "write", "rw"],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),

            vol.Optional("unit", default=defaults.get("unit", "")): str,
            vol.Optional("format", default=defaults.get("format", "")): str,
            vol.Optional("scale", default=defaults.get("scale", 1.0)): vol.Coerce(float),
            vol.Optional("offset", default=defaults.get("offset", 0.0)): vol.Coerce(float),
            vol.Optional("options", default=defaults.get("options", "")): str,
            vol.Optional(
                CONF_BYTE_ORDER,
                default=defaults.get(CONF_BYTE_ORDER, "big")
            ):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(options=["big", "little"])
                ),

            vol.Optional(
                CONF_WORD_ORDER,
                default=defaults.get(CONF_WORD_ORDER, "big")
            ):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(options=["big", "little"])
                ),

        }


        return vol.Schema(schema)

    @staticmethod
    def process_input(user_input: dict, errors: dict, existing: dict | None = None) -> dict | None:
        type_sizes = {
            "uint16": 1, "int16": 1,
            "uint32": 2, "int32": 2,
            "float32": 2,
            "uint64": 4, "int64": 4,
        }

        dtype = user_input.get("data_type")
        if dtype in type_sizes:
            user_input["size"] = type_sizes[dtype]
    
        user_input["address"] = int(user_input["address"])
        user_input["size"] = int(user_input.get("size", 1))
    
        return user_input

    def get_defaults(self, entity):
        return dict(entity)

    def format_label(self, entity):
        return f"{entity.get('name')} @ {entity.get('address')}"

    def merge_template(self, entities, template):
        added = 0
        existing = {(e.get("name"), e.get("address")) for e in entities}
        for e in template:
            key = (e.get("name"), e.get("address"))
            if key not in existing:
                entities.append(e)
                added += 1
        return added


class SNMPSchemaHandler:
    config_key = CONF_ENTITIES

    def get_schema(self, defaults=None):
        defaults = defaults or {}
        return vol.Schema({
            vol.Required("name", default=defaults.get("name")): str,
            vol.Required("address", default=defaults.get("address")): str,
            vol.Optional("read_mode", default="get"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "get", "label": "Get (single value)"},
                        {"value": "walk", "label": "Walk (subtree table)"},
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required("data_type", default=defaults.get("data_type", "string")):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["string", "integer", "counter32", "counter64"],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            vol.Optional("scale", default=defaults.get("scale", 1.0)): vol.Coerce(float),
            vol.Optional("offset", default=defaults.get("offset", 0.0)): vol.Coerce(float),
            vol.Optional("format", default=defaults.get("format", "")): str,
        })

    

    @staticmethod
    def process_input(
        user_input: dict,
        errors: dict,
        existing: dict | None = None,
    ) -> dict | None:
        if not user_input.get("address"):
            errors["address"] = "required"
            return None
        clean = {k: v for k, v in user_input.items() if v not in ("", None)}
        return {
            **(existing or {}),  # preserve old fields
            **clean,        # override edited fields
        }


    def get_defaults(self, entity):
        return dict(entity)

    def format_label(self, entity):
        return f"{entity.get('name')} @ {entity.get('address')}"

    def merge_template(self, entities, template):
        added = 0
        existing = {(e.get("name"), e.get("address")) for e in entities}
        for e in template:
            key = (e.get("name"), e.get("address"))
            if key not in existing:
                entities.append(e)
                added += 1
        return added
