#------------------------------------------
#-- base options_flow.py protocol wizard
#------------------------------------------
# options_flow.py

"""Options flow for Protocol Wizard – protocol-aware but maintains Modbus compatibility."""
from __future__ import annotations
import logging
import json
from datetime import timedelta
import voluptuous as vol
import os

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_UPDATE_INTERVAL,
    CONF_ENTITIES,
    CONF_REGISTERS,
    CONF_PROTOCOL_MODBUS,
#    CONF_PROTOCOL_SNMP,
    CONF_PROTOCOL,
)

_LOGGER = logging.getLogger(__name__)


class ModbusWizardOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Protocol Wizard (currently Modbus-focused)."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        self._config_entry = config_entry  # Use private attribute to store the value (other one is readonly from the base class)
        # Get protocol from entry, default to modbus for backward compatibility
        self.protocol = config_entry.data.get(CONF_PROTOCOL, CONF_PROTOCOL_MODBUS)
        
        # Use protocol-aware config key
        config_key = CONF_REGISTERS if self.protocol == CONF_PROTOCOL_MODBUS else CONF_ENTITIES
        self._entities: list[dict] = list(config_entry.options.get(config_key, []))
        self._edit_index: int | None = None
    
    @property
    def config_entry(self) -> config_entries.ConfigEntry:
        """Return the config entry."""
        return self._config_entry        
    
    async def async_step_init(self, user_input=None):
        menu_options = {
            "settings": "Settings",
            "add_entity": "Add Entity",
            "load_template": "Load device template",
        }
        if len(self._entities) > 0:
            menu_options["list_entities"] = f"Entities ({len(self._entities)})"
            menu_options["edit_entity"] = "Edit Entity"
        return self.async_show_menu(
            step_id="init",
            menu_options=menu_options,
        )

    # ------------------------------------------------------------------
    # Edit
    # ------------------------------------------------------------------
    async def async_step_edit_entity(self, user_input=None):
        """Select which entity to edit."""
        if user_input is not None:
            self._edit_index = int(user_input["register"])
            return await self.async_step_edit_entity_form()
    
        # Create dropdown options: index -> display label
        options = [
            selector.SelectOptionDict(
                value=str(i),
                label=f"{r['name']} (Address {r['address']}, {r.get('data_type', 'uint16')})"
            )
            for i, r in enumerate(self._entities)
        ]
    
        return self.async_show_form(
            step_id="edit_entity",
            data_schema=vol.Schema({
                vol.Required("register"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }),
        )
        
    # ------------------------------------------------------------------
    # EDIT ENTITY FORM
    # ------------------------------------------------------------------
    
    async def async_step_edit_entity_form(self, user_input=None):
        """Edit the selected entity."""
        reg = self._entities[self._edit_index]
        errors = {}
    
        if user_input is not None:
            # Parse options JSON
            raw_opts = user_input.get("options")
            if raw_opts:
                try:
                    user_input["options"] = json.loads(raw_opts)
                except json.JSONDecodeError:
                    errors["options"] = "invalid_json"
    
            # Get protocol-specific schema handler
            schema_handler = self._get_schema_handler()
            processed_input = schema_handler.process_input(user_input)
            
            if processed_input and not errors:
                self._entities[self._edit_index] = processed_input
                self._save_options()
                _LOGGER.info("Entity '%s' updated", processed_input.get("name"))
                return await self.async_step_init()
    
        # Prepare defaults from existing entity
        defaults = {
            "name": reg.get("name"),
            "address": reg.get("address"),
            "data_type": reg.get("data_type", "uint16"),
            "register_type": reg.get("register_type", "auto"),
            "rw": reg.get("rw", "read"),
            "unit": reg.get("unit", ""),
            "scale": reg.get("scale", 1.0),
            "offset": reg.get("offset", 0.0),
            "options": json.dumps(reg.get("options", {})) if reg.get("options") else "",
            "byte_order": reg.get("byte_order", "big"),
            "word_order": reg.get("word_order", "big"),
            "allow_bits": reg.get("allow_bits", False),
            "min": reg.get("min"),
            "max": reg.get("max"),
            "step": reg.get("step", 1),
        }

        schema_handler = self._get_schema_handler()
        return self.async_show_form(
            step_id="edit_entity_form",
            data_schema=schema_handler.get_schema(defaults),
            errors=errors,
        )
    
    # ------------------------------------------------------------------
    # SETTINGS
    # ------------------------------------------------------------------
    async def async_step_settings(self, user_input=None):
        if user_input is not None:
            interval = user_input[CONF_UPDATE_INTERVAL]

            coordinator = (
                self.hass.data
                .get(DOMAIN, {})
                .get("coordinators", {})
                .get(self._config_entry.entry_id)
            )
            if coordinator:
                coordinator.update_interval = timedelta(seconds=interval)
                _LOGGER.debug("Updated coordinator interval to %d seconds", interval)

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
    # ADD ENTITY
    # ------------------------------------------------------------------

    async def async_step_add_entity(self, user_input=None):
        errors = {}

        if user_input is not None:
            # Parse options (SelectEntity)
            raw_opts = user_input.get("options")
            if raw_opts:
                try:
                    user_input["options"] = json.loads(raw_opts)
                except json.JSONDecodeError:
                    errors["options"] = "invalid_json"

            # Get protocol-specific schema handler
            schema_handler = self._get_schema_handler()
            processed_input = schema_handler.process_input(user_input)
            
            if processed_input and not errors:
                _LOGGER.debug("Adding entity: %s", processed_input)
                self._entities.append(processed_input)
                self._save_options()
                _LOGGER.info("Entity added. Total: %d", len(self._entities))
                return await self.async_step_init()

        schema_handler = self._get_schema_handler()
        return self.async_show_form(
            step_id="add_entity",
            data_schema=schema_handler.get_schema(),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # LIST / DELETE
    # ------------------------------------------------------------------

    async def async_step_list_entities(self, user_input=None):
        """List and optionally delete entities."""
        if user_input is not None:
            delete = set(user_input.get("delete", []))
            if delete:
                self._entities = [
                    r for i, r in enumerate(self._entities)
                    if str(i) not in delete
                ]
                self._save_options()
                _LOGGER.info("Deleted %d entities. Remaining: %d", len(delete), len(self._entities))
            return await self.async_step_init()

        options = [
            selector.SelectOptionDict(
                value=str(i),
                label=f"{r['name']} (Address {r['address']}, {r.get('data_type', 'uint16')})"
            )
            for i, r in enumerate(self._entities)
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
    # TEMPLATE HELPERS
    # ------------------------------------------------------------------
    @staticmethod
    def _load_template_file(path: str):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    # ------------------------------------------------------------------
    # Load Template
    # ------------------------------------------------------------------
    async def async_step_load_template(self, user_input=None):
        if user_input and "template" in user_input:
            template_name = user_input["template"]
            template_path = self.hass.config.path(
                "custom_components", DOMAIN, "templates", f"{template_name}.json"
            )
    
            try:
                template_data = await self.hass.async_add_executor_job(
                    self._load_template_file, template_path
                )
    
                if not isinstance(template_data, list):
                    raise ValueError("Template must be a list")
    
                existing_keys = {
                    (r.get("name"), r.get("address"))
                    for r in self._entities
                }
    
                added = 0
                for reg in template_data:
                    if not isinstance(reg, dict):
                        continue
                    if "name" not in reg or "address" not in reg:
                        continue
    
                    key = (reg["name"], reg["address"])
                    if key in existing_keys:
                        continue
                    
                    reg["address"] = int(reg["address"])
                    reg["size"] = int(reg.get("size", 1))
                    self._entities.append(reg)
                    existing_keys.add(key)
                    added += 1
    
                if not added:
                    return self.async_show_form(
                        step_id="load_template",
                        errors={"base": "template_empty_or_duplicate"},
                    )
    
                self._save_options()
                return await self.async_step_init()
    
            except FileNotFoundError:
                return self.async_show_form(
                    step_id="load_template",
                    errors={"base": "template_not_found"},
                )
            except json.JSONDecodeError:
                return self.async_show_form(
                    step_id="load_template",
                    errors={"base": "invalid_template"},
                )
            except Exception as err:
                _LOGGER.error("Failed to load template %s: %s", template_name, err)
                return self.async_show_form(
                    step_id="load_template",
                    errors={"base": "load_failed"},
                )
    
        # List templates
        templates_dir = self.hass.config.path(
            "custom_components", DOMAIN, "templates"
        )
    
        try:
            templates = sorted(
                f[:-5]
                for f in os.listdir(templates_dir)
                if f.endswith(".json")
            )
        except Exception:
            templates = []
    
        if not templates:
            return self.async_abort(reason="no_templates")
    
        return self.async_show_form(
            step_id="load_template",
            data_schema=vol.Schema({
                vol.Required("template"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=t,
                                label=t.replace("_", " ").title(),
                            )
                            for t in templates
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }),
        )

    # ------------------------------------------------------------------
    # PROTOCOL-SPECIFIC SCHEMA HANDLERS
    # ------------------------------------------------------------------
    
    def _get_schema_handler(self):
        """Get protocol-specific schema handler."""
        if self.protocol == CONF_PROTOCOL_MODBUS:
            return ModbusSchemaHandler()
       # elif self.protocol == CONF_PROTOCOL_SNMP: return SNMPSchemaHandler()
        return ModbusSchemaHandler()  # Default
    
    def _save_options(self, updates: dict | None = None) -> None:
        """Save options, using protocol-aware config key."""
        new_options = dict(self._config_entry.options)
        
        # Use protocol-specific config key
        config_key = CONF_REGISTERS if self.protocol == CONF_PROTOCOL_MODBUS else CONF_ENTITIES
        
        if updates:
            new_options.update(updates)
        else:
            # Ensure numeric fields are correct type
            for r in self._entities:
                r["address"] = int(r["address"])
                r["size"] = int(r.get("size", 1))
            new_options[config_key] = self._entities
        
        self.hass.config_entries.async_update_entry(
            self._config_entry,
            options=new_options,
        )
        
        # Trigger reload
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(self._config_entry.entry_id)
        )


# ------------------------------------------------------------------
# PROTOCOL-SPECIFIC SCHEMA HANDLERS
# ------------------------------------------------------------------

class ModbusSchemaHandler:
    """Handles Modbus-specific schema and input processing."""
    
    @staticmethod
    def get_schema(defaults: dict | None = None) -> vol.Schema:
        """Get Modbus entity schema."""
        defaults = defaults or {}
        
        return vol.Schema({
            vol.Required("name", default=defaults.get("name")): str,
            vol.Required("address", default=defaults.get("address")): 
                vol.All(vol.Coerce(int), vol.Range(min=0, max=65535)),
            
            vol.Required("data_type", default=defaults.get("data_type", "uint16")): 
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["uint16", "int16", "uint32", "int32", "float32", "uint64", "int64"],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),

            vol.Required("register_type", default=defaults.get("register_type", "input")): 
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["auto", "holding", "input", "coil", "discrete"],
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
            vol.Optional("options", default=defaults.get("options", "")): str,
            
            vol.Optional("byte_order", default=defaults.get("byte_order", "big")): 
                selector.SelectSelector(
                    selector.SelectSelectorConfig(options=["big", "little"])
                ),
            
            vol.Optional("word_order", default=defaults.get("word_order", "big")): 
                selector.SelectSelector(
                    selector.SelectSelectorConfig(options=["big", "little"])
                ),
            
            vol.Optional("allow_bits", default=defaults.get("allow_bits", False)): bool,
            vol.Optional("min", default=defaults.get("min")): vol.Any(None, vol.Coerce(float)),
            vol.Optional("max", default=defaults.get("max")): vol.Any(None, vol.Coerce(float)),
            vol.Optional("step", default=defaults.get("step", 1)): vol.Coerce(float),
        })
    
    @staticmethod
    def process_input(user_input: dict) -> dict | None:
        """Process and validate Modbus-specific input."""
        # Enforce size from datatype
        type_sizes = {
            "uint16": 1, "int16": 1,
            "uint32": 2, "int32": 2,
            "float32": 2,
            "uint64": 4, "int64": 4,
        }
        dtype = user_input.get("data_type")
        if dtype in type_sizes:
            user_input["size"] = type_sizes[dtype]

        # Ensure numeric fields are correct type
        user_input["address"] = int(user_input["address"])
        user_input["size"] = int(user_input.get("size", 1))
        
        return user_input
