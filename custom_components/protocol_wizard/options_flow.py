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

        config_key = self.schema_handler.config_key
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
            processed = self.schema_handler.process_input(user_input, errors)
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
            processed = self.schema_handler.process_input(user_input, errors)
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
        if user_input:
            name = user_input["template"]
            path = self.hass.config.path(
                "custom_components", DOMAIN, "templates", f"{name}.json"
            )

            try:
                data = await self.hass.async_add_executor_job(self._load_template, path)
                added = self.schema_handler.merge_template(self._entities, data)
                if not added:
                    return self.async_show_form(
                        step_id="load_template",
                        errors={"base": "template_empty_or_duplicate"},
                    )
                self._save_entities()
                return await self.async_step_init()
            except Exception as err:
                _LOGGER.error("Template load failed: %s", err)
                return self.async_show_form(
                    step_id="load_template",
                    errors={"base": "load_failed"},
                )

        templates = []
        templates_dir = self.hass.config.path("custom_components", DOMAIN, "templates")
        try:
            templates = sorted(f[:-5] for f in os.listdir(templates_dir) if f.endswith(".json"))
        except Exception:
            pass

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
        )

    # ------------------------------------------------------------------
    # INTERNAL
    # ------------------------------------------------------------------

    @staticmethod
    def _load_template(path: str):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_entities(self):
        options = dict(self._config_entry.options)
        options[self.schema_handler.config_key] = self._entities
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
            vol.Optional("scale", default=defaults.get("scale", 1.0)): vol.Coerce(float),
            vol.Optional("offset", default=defaults.get("offset", 0.0)): vol.Coerce(float),

            # 👇 the important switch
            vol.Optional(CONF_ADVANCED, default=defaults.get(CONF_ADVANCED, False)): bool,
        }

        # Append advanced fields *only when enabled*
        if defaults.get(CONF_ADVANCED):
            schema.update(ModbusSchemaHandler._advanced_schema(defaults))

        return vol.Schema(schema)
        
    @staticmethod
    def _advanced_schema(defaults: dict) -> dict:
        return {
            vol.Optional(
                CONF_REGISTER_TYPE,
                default=defaults.get(CONF_REGISTER_TYPE, "auto")
            ):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["auto", "holding", "input", "coil", "discrete"],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),

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

            vol.Optional(
                CONF_ALLOW_BITS,
                default=defaults.get(CONF_ALLOW_BITS, False)
            ): bool,
        }

    def process_input(self, data, errors):
        data["address"] = int(data["address"])
        return data

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
            vol.Required("data_type", default=defaults.get("data_type", "string")):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["string", "integer", "counter32", "counter64"],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
        })

    @staticmethod
    def process_input(user_input: dict) -> dict | None:
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

        # Do NOT touch advanced fields here
        # Decoder / entity will interpret them later

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
