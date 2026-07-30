#------------------------------------------
# options_flow.py – Protocol Wizard (protocol-agnostic)
#------------------------------------------
"""Options flow for Protocol Wizard – fully protocol-agnostic."""
from __future__ import annotations

import json
import logging
from datetime import timedelta

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import selector

#import asyncio
from .const import (
    CONF_BACNET_DEVICES,
    CONF_BYTE_ORDER,
    CONF_ENTITIES,
    CONF_PROTOCOL,
    CONF_PROTOCOL_BACNET,
    CONF_PROTOCOL_MODBUS,
    CONF_PROTOCOL_MQTT,
    CONF_PROTOCOL_SNMP,
    CONF_REGISTER_TYPE,
    CONF_REGISTERS,
    CONF_SLAVES,
    CONF_UPDATE_INTERVAL,
    CONF_WORD_ORDER,
    DOMAIN,
)
from .template_utils import (
    delete_template,
    get_available_templates,
    get_template_dropdown_choices,
    load_template,
    save_template,
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
        
        # NEW: Track which slave we're configuring (for Modbus multi-slave)
        self._selected_slave_index: int | None = None

        # Load entities based on context
        self._entities: list[dict] = self._load_entities_for_context()
        self._edit_index: int | None = None

    @property
    def config_entry(self) -> config_entries.ConfigEntry:
        return self._config_entry
    
    def _load_entities_for_context(self) -> list[dict]:
        """Load entities based on current context (slave/device or global)."""
        if self.protocol == CONF_PROTOCOL_MODBUS:
            # Check if we're in slave context
            if self._selected_slave_index is not None:
                slaves = self._config_entry.options.get(CONF_SLAVES, [])
                if slaves and self._selected_slave_index < len(slaves):
                    return list(slaves[self._selected_slave_index].get('registers', []))
            # Check if we have slaves (multi-slave mode)
            slaves = self._config_entry.options.get(CONF_SLAVES, [])
            if slaves and len(slaves) > 0:
                # Multi-slave mode but no specific slave selected
                # Check if this is a migrated single-slave (backward compat)
                if len(slaves) == 1:
                    # Single slave - load its entities
                    return list(slaves[0].get('registers', []))
                # Multiple slaves - return empty, user must select a slave
                return []
            # No slaves yet - backward compat mode
            return list(self._config_entry.options.get(CONF_REGISTERS, []))
        elif self.protocol == CONF_PROTOCOL_BACNET:
            # BACnet uses bacnet_devices structure (similar to Modbus slaves)
            bacnet_devices = self._config_entry.options.get(CONF_BACNET_DEVICES, [])
            if bacnet_devices and len(bacnet_devices) > 0:
                # Load from first device's entities
                return list(bacnet_devices[0].get('entities', []))
            # Fallback to old structure (backward compat)
            return list(self._config_entry.options.get(CONF_ENTITIES, []))
        else:
            # Other protocols (SNMP, MQTT, etc.)
            return list(self._config_entry.options.get(CONF_ENTITIES, []))
        
    @staticmethod
    def _export_schema():
        return vol.Schema({
            vol.Required("name"): str
        })
        
    @staticmethod
    def _write_template(path: str, entities: list[dict]):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entities, f, indent=2)
    # ------------------------------------------------------------------
    # INIT
    # ------------------------------------------------------------------

    async def async_step_init(self, user_input=None):
        menu_options = {
            "settings": "Settings",
        }

        # For Modbus with slaves structure, show slave selection
        if self.protocol == CONF_PROTOCOL_MODBUS:
            slaves = self._config_entry.options.get(CONF_SLAVES, [])
            if slaves:
                # Show slave management menu (allows adding more slaves)
                slave_count = len(slaves)
                if slave_count == 1:
                    menu_options["select_slave"] = "Manage Slaves (1 slave, add more)"
                else:
                    menu_options["select_slave"] = f"Manage Slaves ({slave_count} slaves)"

                # If single slave, also show entity shortcuts for convenience
                if slave_count == 1:
                    menu_options["add_entity"] = "Add entity (quick)"
                    if self._entities:
                        menu_options["list_entities"] = f"Entities ({len(self._entities)})"
                        menu_options["edit_entity"] = "Edit entity (quick)"
            else:
                # No slaves - backward compat mode
                menu_options["add_entity"] = "Add entity"
                if self._entities:
                    menu_options["list_entities"] = f"Entities ({len(self._entities)})"
                    menu_options["edit_entity"] = "Edit entity"
        else:
            # Non-Modbus: normal entity management
            menu_options["add_entity"] = "Add entity"
            if self._entities:
                menu_options["list_entities"] = f"Entities ({len(self._entities)})"
                menu_options["edit_entity"] = "Edit entity"

        # Template options
        # For multi-slave Modbus, only show template options if single slave or within slave context
        if self.protocol == CONF_PROTOCOL_MODBUS:
            slaves = self._config_entry.options.get(CONF_SLAVES, [])
            if len(slaves) <= 1:
                menu_options["load_template"] = "Load template"
        else:
            menu_options["load_template"] = "Load template"
        menu_options.update({
            "export_template": "Export template",
            "delete_template": "Delete user template",
        })

        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_select_slave(self, user_input=None):
        """Select which slave to configure."""
        if user_input:
            action = user_input.get("action")
            
            if action == "add_slave":
                return await self.async_step_add_slave()
            elif action.startswith("configure_"):
                # Extract slave index
                idx = int(action.split("_")[1])
                self._selected_slave_index = idx
                self._entities = self._load_entities_for_context()
                return await self.async_step_slave_menu()
            elif action.startswith("delete_"):
                # Delete slave
                idx = int(action.split("_")[1])
                slaves = list(self._config_entry.options.get(CONF_SLAVES, []))
                if idx < len(slaves):
                    deleted = slaves.pop(idx)
                    deleted_slave_id = deleted.get('slave_id')

                    # Clean up device registry entry for this slave
                    device_registry = dr.async_get(self.hass)
                    coordinator_key = f"{self._config_entry.entry_id}_slave_{deleted_slave_id}"
                    device = device_registry.async_get_device(identifiers={(DOMAIN, coordinator_key)})
                    if device:
                        device_registry.async_remove_device(device.id)
                        _LOGGER.info("Removed device for slave %d from device registry", deleted_slave_id)

                    options = dict(self._config_entry.options)
                    options[CONF_SLAVES] = slaves
                    self.hass.config_entries.async_update_entry(self._config_entry, options=options)
                    await self.hass.config_entries.async_reload(self._config_entry.entry_id)
                    _LOGGER.info("Deleted slave: %s", deleted.get('name'))
                return await self.async_step_init()
        
        slaves = self._config_entry.options.get(CONF_SLAVES, [])
        
        options = {"add_slave": "➕ Add New Slave"}
        for idx, slave in enumerate(slaves):
            name = slave.get('name', f"Slave {slave['slave_id']}")
            slave_id = slave['slave_id']
            entity_count = len(slave.get('registers', []))
            options[f"configure_{idx}"] = f"{name} (ID {slave_id}) - {entity_count} entities"
            options[f"delete_{idx}"] = f"Delete: {name} (ID {slave_id})"
        
        return self.async_show_form(
            step_id="select_slave",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In(options)
            }),
            description_placeholders={
                "info": "Select a slave to configure its entities, or add a new slave"
            }
        )
    
    async def async_step_slave_menu(self, user_input=None):
        """Menu for managing a specific slave's entities."""
        if self._selected_slave_index is None:
            return await self.async_step_init()
        
        slaves = self._config_entry.options.get(CONF_SLAVES, [])
        if not slaves or self._selected_slave_index >= len(slaves):
            return await self.async_step_init()
        
  #      slave = slaves[self._selected_slave_index]
   #     slave_name = slave.get('name', f"Slave {slave['slave_id']}")
        
        menu_options = {
            "add_entity": "Add entity",
            "load_template": "Load template for this slave",
        }
        
        if self._entities:
            menu_options["list_entities"] = f"Entities ({len(self._entities)})"
            menu_options["edit_entity"] = "Edit entity"
        
        menu_options["back"] = "← Back to slave list"
        
        return self.async_show_menu(
            step_id="slave_menu",
            menu_options=menu_options,
        )

    async def async_step_back(self, user_input=None):
        """Go back to main menu."""
        # Clear slave selection
        self._selected_slave_index = None
        self._entities = self._load_entities_for_context()
        return await self.async_step_init()

    async def async_step_add_slave(self, user_input=None):
        """Add a new slave to this connection."""
        errors = {}
        
        if user_input:
            slaves = list(self._config_entry.options.get(CONF_SLAVES, []))
            
            # Check for duplicate slave_id
            new_slave_id = user_input["slave_id"]
            if any(s["slave_id"] == new_slave_id for s in slaves):
                errors["base"] = "duplicate_slave_id"
            else:
                # Build new slave entry
                new_slave = {
                    "slave_id": new_slave_id,
                    "name": user_input.get("name", f"Slave {new_slave_id}"),
                    "registers": []  # Start with empty entity list
                }
                
                # Handle template if selected
                template_name = user_input.get("template")
                if template_name and template_name != "none":
                    new_slave["template"] = template_name
                    # Template will be loaded on next integration reload by __init__.py
                
                slaves.append(new_slave)
                
                new_options = dict(self._config_entry.options)
                new_options[CONF_SLAVES] = slaves
                
                self.hass.config_entries.async_update_entry(self._config_entry, options=new_options)
                
                # Reload to apply
                await self.hass.config_entries.async_reload(self._config_entry.entry_id)
                
                return await self.async_step_init()
        
        # Get available templates
        templates = await get_available_templates(self.hass, self.protocol)
        template_choices = {"none": "No template (add entities manually)"}
        template_choices.update(get_template_dropdown_choices(templates))
        
        schema_dict = {
            vol.Required("slave_id"): vol.All(vol.Coerce(int), vol.Range(min=1, max=247)),
            vol.Optional("name"): str,
        }
        
        if templates:
            schema_dict[vol.Optional("template", default="none")] = vol.In(template_choices)
        
        return self.async_show_form(
            step_id="add_slave",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={
                "info": "Add a new Modbus slave device. Optionally select a template to pre-configure entities."
            }
        )
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
            # Reload entities to get current state
            self._entities = self._load_entities_for_context()
            
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
            if user_input.get("delete_all"):
                self._entities = []
            else:
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
                vol.Optional("delete_all", default=False): bool,
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
    async def async_step_delete_template(self, user_input=None):
        """Delete a user template."""
        if user_input:
            template_id = user_input["template"]
            
            success, message = await delete_template(
                self.hass,
                self.protocol,
                template_id
            )
            
            if not success:
                return self.async_show_form(
                    step_id="delete_template",
                    data_schema=self._get_delete_template_schema(),
                    errors={"base": "delete_failed"},
                    description_placeholders={"error": message}
                )
            
            return self.async_abort(reason="template_deleted")
        
        # Get only user templates
        all_templates = await get_available_templates(self.hass, self.protocol)
        user_templates = {
            tid: info for tid, info in all_templates.items()
            if tid.startswith("user:")
        }
        dropdown_choices = get_template_dropdown_choices(user_templates)
        
        if not dropdown_choices:
            return self.async_abort(reason="no_user_templates")
        
        return self.async_show_form(
            step_id="delete_template",
            data_schema=vol.Schema({
                vol.Required("template"): vol.In(dropdown_choices)
            })
        )
    async def async_step_load_template(self, user_input=None):
        """Load a device template."""
        if user_input:
            template_id = user_input["template"]
            
            entities = await load_template(self.hass, self.protocol, template_id)
            
            if not entities:
                return self.async_show_form(
                    step_id="load_template",
                    data_schema=self._get_template_schema(),
                    errors={"base": "template_not_found"},
                )
            
            # IMPORTANT: Reload entities from current config state
            # (migration may have run since __init__)
            self._entities = self._load_entities_for_context()
            
            added = self.schema_handler.merge_template(self._entities, entities)
            
            if added == 0:
                return self.async_show_form(
                    step_id="load_template",
                    data_schema=self._get_template_schema(),
                    errors={"base": "template_empty_or_duplicate"},
                )
            
            self._save_entities()
            return await self.async_step_init() # must go back to options flow to avoid race condition reloading entities
        
        # Get templates for dropdown
        templates = await get_available_templates(self.hass, self.protocol)
        dropdown_choices = get_template_dropdown_choices(templates)
        
        if not dropdown_choices:
            return self.async_abort(reason="no_templates")
        
        return self.async_show_form(
            step_id="load_template",
            data_schema=vol.Schema({
                vol.Required("template"): vol.In(dropdown_choices)
            })
        )
    # ------------------------------------------------------------------
    # Export template
    # ------------------------------------------------------------------
    async def async_step_export_template(self, user_input=None):
        if user_input:
            name = user_input["name"].strip()
            to_user_dir = user_input.get("save_to_user_dir", True)
            
            if not name:
                return self.async_show_form(
                    step_id="export_template",
                    data_schema=self._export_schema(),
                    errors={"name": "required"},
                )
            
            # Optional: Get device metadata for richer templates
            metadata = {
                "name": name,
                "description": f"Exported from {self.config_entry.title}",
                "protocol": self.protocol,
            }
            
            success, message = await save_template(
                self.hass,
                self.protocol,
                name,
                self._entities,
                metadata=metadata,
                to_user_dir=to_user_dir
            )
            
            if not success:
                return self.async_show_form(
                    step_id="export_template",
                    data_schema=self._export_schema(),
                    errors={"base": "export_failed"},
                    description_placeholders={"error": message}
                )
            
            #Success - close the dialog!
            return self.async_abort(reason="template_exported")
        
        return self.async_show_form(
            step_id="export_template",
            data_schema=self._export_schema()
        )
        
    def _export_schema(self):
        """Get export template schema."""
        return vol.Schema({
            vol.Required("name"): str,
            vol.Optional("save_to_user_dir", default=True): bool,  # NEW!
        })
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

        if self.protocol == CONF_PROTOCOL_MODBUS:
            # Check if we're in slave context
            if self._selected_slave_index is not None:
                # Save to specific slave's registers
                slaves = list(options.get(CONF_SLAVES, []))
                if slaves and self._selected_slave_index < len(slaves):
                    slaves[self._selected_slave_index]['registers'] = self._entities
                    options[CONF_SLAVES] = slaves
            else:
                # Check if we have slaves at all
                slaves = list(options.get(CONF_SLAVES, []))
                if slaves:
                    # Single slave mode - save to first slave
                    slaves[0]['registers'] = self._entities
                    options[CONF_SLAVES] = slaves
                else:
                    # True backward compat: no slaves exist yet
                    options[CONF_REGISTERS] = self._entities
        elif self.protocol == CONF_PROTOCOL_BACNET:
            # BACnet uses bacnet_devices structure (similar to Modbus slaves)
            bacnet_devices = list(options.get(CONF_BACNET_DEVICES, []))
            if bacnet_devices:
                # Save to first device's entities
                bacnet_devices[0]['entities'] = self._entities
                options[CONF_BACNET_DEVICES] = bacnet_devices
                _LOGGER.info("[Options Flow] Saved %d entities to BACnet device %d",
                            len(self._entities), bacnet_devices[0]['device_id'])
            else:
                # Fallback to old structure (shouldn't happen)
                options[CONF_ENTITIES] = self._entities
                _LOGGER.warning("[Options Flow] No bacnet_devices found, using fallback")
        else:
            # Other protocols (SNMP, MQTT, etc.)
            options[CONF_ENTITIES] = self._entities
        
        # Update entry (synchronous)
        self.hass.config_entries.async_update_entry(self._config_entry, options=options)
        
        # Schedule reload in background (fire and forget)
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(self._config_entry.entry_id)
        )

    def _save_options(self, updates: dict):
        options = dict(self._config_entry.options)
        options.update(updates)
        # strangely, this one does not need an await...
        self.hass.config_entries.async_update_entry(self._config_entry, options=options)

    def _get_schema_handler(self):
        if self.protocol == CONF_PROTOCOL_SNMP:
            return SNMPSchemaHandler()
        elif self.protocol == CONF_PROTOCOL_MQTT:
            return MQTTSchemaHandler()
        elif self.protocol == CONF_PROTOCOL_BACNET:
            return BACnetSchemaHandler()
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
            vol.Optional("device_class", default=defaults.get("device_class", " ")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[" ", "temperature", "power", "energy", "voltage", "current", "frequency", "duration"],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("state_class", default=defaults.get("state_class", " ")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[" ", "measurement", "total", "total_increasing"],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("entity_category", default=defaults.get("entity_category", " ")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[" ", "diagnostic", "config", "system"],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("icon", default=defaults.get("icon", "")): str,  # e.g. mdi:thermometer
            vol.Optional("unit", default=defaults.get("unit", "")): str,
            vol.Optional("min", default=0.0): vol.Coerce(float),
            vol.Optional("max", default=65535.0 if "uint" in defaults.get("data_type", "") else 100.0): vol.Coerce(float),
            vol.Optional("step", default=0.1 if "float" in defaults.get("data_type", "") else 1.0): vol.Coerce(float),
            vol.Optional("format", default=defaults.get("format", "")): str,
            vol.Optional("scale", default=defaults.get("scale", 1.0)): vol.Coerce(float),
            vol.Optional("offset", default=defaults.get("offset", 0.0)): vol.Coerce(float),
            vol.Optional("options", default=defaults.get("options", "")): str,   # options: JSON string mapping raw values to labels
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
        """
        Process user input for Modbus entity.
        Handles both new entities and edits, preserving old fields.
        """
        # Required validation first - check for None/missing, not falsy (0 is valid!)
        if "address" not in user_input or user_input.get("address") is None or user_input.get("address") == "":
            errors["address"] = "required"
            return None
        
        # Start with existing data (for edits) or empty dict
        processed = dict(existing) if existing else {}
        if "options" in processed and isinstance(processed["options"], str):
            try:
                processed["options"] = json.loads(processed["options"])
                if not isinstance(processed["options"], dict):
                    processed["options"]="" # if it is rubish, we dont use it
            except Exception:
                errors["options"] = ""
        # Update with new values, handling empty strings properly
        for key, value in user_input.items():
            if value in (" ","", None):
                processed.pop(key, None)  # Clear if empty
            elif value is not None:
                processed[key] = value        
        # Calculate size based on data_type
        type_sizes = {
            "uint16": 1, "int16": 1,
            "uint32": 2, "int32": 2,
            "float32": 2,
            "uint64": 4, "int64": 4,
        }
        dtype = processed.get("data_type")
        if dtype in type_sizes:
            processed["size"] = type_sizes[dtype]
        
        # Convert types
        try:
            processed["address"] = int(processed["address"])
            processed["size"] = int(processed.get("size", 1))
            processed["scale"] = float(processed.get("scale", 1.0))
            processed["offset"] = float(processed.get("offset", 0.0))
        except (ValueError, TypeError) as err:
            _LOGGER.error("Type conversion error: %s", err)
            errors["address"] = "invalid_number"
            return None
        
        # Ensure required fields exist with defaults
        processed.setdefault("register_type", "input")
        processed.setdefault("data_type", "uint16")
        processed.setdefault("rw", "read")
        processed.setdefault("byte_order", "big")
        processed.setdefault("word_order", "big")
        processed.setdefault("scale", 1.0)
        processed.setdefault("offset", 0.0)
        
        return processed

    def get_defaults(self, entity):
        """
        Get defaults for editing an entity.
        Returns the entity dict with all fields, using empty string for missing optional fields.
        """
        defaults = dict(entity)
        
        # Set empty string for optional fields that don't exist
        # (so form shows them as empty rather than None)
        defaults.setdefault("device_class", " ") # to ensure it work in dropdown
        defaults.setdefault("state_class", " ")
        defaults.setdefault("entity_category", " ")
        defaults.setdefault("icon", "")
        defaults.setdefault("unit", "")
        defaults.setdefault("format", "")
        opts = defaults.get("options")
        if isinstance(opts, dict):
            defaults["options"] = json.dumps(opts)
        else:
            defaults.setdefault("options", "")
        
        # Ensure numeric fields have values
        defaults.setdefault("scale", 1.0)
        defaults.setdefault("offset", 0.0)
        
        return defaults

    def format_label(self, entity):
        return f"{entity.get('name')} @ {entity.get('address')}"

    def merge_template(self, entities, template):
        """Merge template entities, processing each to add defaults."""
        added = 0
        existing = {(e.get("name"), e.get("address")) for e in entities}
        
        for template_entity in template:
            key = (template_entity.get("name"), template_entity.get("address"))
            if key not in existing:
                # Process template entity to add missing defaults
                errors = {}
                processed = self.process_input(template_entity, errors, existing=None)
                if processed and not errors:
                    entities.append(processed)
                    added += 1
                else:
                    _LOGGER.warning("Skipped invalid template entity: %s (errors: %s)", 
                                  template_entity.get("name"), errors)
        
        return added

class BACnetSchemaHandler:
    """Schema handler for BACnet entities."""
    
    config_key = CONF_ENTITIES  # BACnet uses 'entities' key
    
    def get_schema(self, defaults=None):
        """Return the schema for BACnet entity configuration."""
        defaults = defaults or {}
        
        return vol.Schema({
            vol.Required("name", default=defaults.get("name")): str,
            
            # BACnet address format: "objectType:instance:property"
            vol.Required("address", default=defaults.get("address")): str,
            
            # Object type dropdown
            vol.Optional("object_type_helper", default=defaults.get("object_type_helper", "analogInput")):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "analogInput", "label": "Analog Input"},
                            {"value": "analogOutput", "label": "Analog Output"},
                            {"value": "analogValue", "label": "Analog Value"},
                            {"value": "binaryInput", "label": "Binary Input"},
                            {"value": "binaryOutput", "label": "Binary Output"},
                            {"value": "binaryValue", "label": "Binary Value"},
                            {"value": "multiStateInput", "label": "Multi-State Input"},
                            {"value": "multiStateOutput", "label": "Multi-State Output"},
                            {"value": "multiStateValue", "label": "Multi-State Value"},
                            {"value": "accumulator", "label": "Accumulator"},
                            {"value": "device", "label": "Device"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            
            # Data type
            vol.Required("data_type", default=defaults.get("data_type", "float")):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "float", "label": "Float (Decimal)"},
                            {"value": "integer", "label": "Integer (Whole Number)"},
                            {"value": "boolean", "label": "Boolean (True/False)"},
                            {"value": "string", "label": "String (Text)"},
                            {"value": "enumerated", "label": "Enumerated (Options)"},
                            {"value": "unsigned", "label": "Unsigned Integer"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            
            # Read/Write mode
            vol.Optional("rw", default=defaults.get("rw", "read")):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "read", "label": "Read Only"},
                            {"value": "write", "label": "Write Only"},
                            {"value": "rw", "label": "Read/Write"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            
            # Write priority (for writable entities)
            vol.Optional("write_priority", default=defaults.get("write_priority", 8)):
                vol.All(vol.Coerce(int), vol.Range(min=1, max=16)),
            
            # Home Assistant metadata
            vol.Optional("device_class", default=defaults.get("device_class", " ")):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            " ",
                            "temperature",
                            "humidity", 
                            "pressure",
                            "power",
                            "energy",
                            "voltage",
                            "current",
                            "frequency",
                            "duration",
                            "illuminance",
                            "gas",
                            "moisture",
                            "pm25",
                            "carbon_dioxide",
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            
            vol.Optional("state_class", default=defaults.get("state_class", " ")):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[" ", "measurement", "total", "total_increasing"],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            
            vol.Optional("entity_category", default=defaults.get("entity_category", " ")):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[" ", "diagnostic", "config"],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            
            vol.Optional("icon", default=defaults.get("icon", "")): str,
            vol.Optional("unit", default=defaults.get("unit", "")): str,
            
            # Value transformation
            vol.Optional("scale", default=defaults.get("scale", 1.0)): vol.Coerce(float),
            vol.Optional("offset", default=defaults.get("offset", 0.0)): vol.Coerce(float),
            vol.Optional("format", default=defaults.get("format", "")): str,
            
            # Options mapping (JSON string)
            vol.Optional("options", default=defaults.get("options", "")): str,
            
            # Number entity constraints (for writable numeric entities)
            vol.Optional("min", default=defaults.get("min", 0.0)): vol.Coerce(float),
            vol.Optional("max", default=defaults.get("max", 100.0)): vol.Coerce(float),
            vol.Optional("step", default=defaults.get("step", 1.0)): vol.Coerce(float),
        })
    
    
    def process_input(self, user_input, errors, existing=None):
        """Process and validate BACnet entity input."""
        # Start with existing data (for edits) or empty dict
        processed = dict(existing) if existing else {}
        
        # Update with new values
        processed.update(user_input)
        
        # Validate address format
        address = processed.get("address", "").strip()
        if not address:
            errors["address"] = "Address is required"
            return None
        
        # Validate BACnet address format: "objectType:instance:property"
        parts = address.split(":")
        if len(parts) != 3:
            errors["address"] = "Invalid format. Expected: objectType:instance:property"
            return None
        
        # Validate instance is a number
        try:
            instance = int(parts[1])
            if instance < 0 or instance > 4194303:
                errors["address"] = "Instance must be between 0 and 4194303"
                return None
        except ValueError:
            errors["address"] = "Instance must be a number"
            return None
        
        # Validate write priority
        try:
            priority = int(processed.get("write_priority", 8))
            if priority < 1 or priority > 16:
                errors["write_priority"] = "Priority must be between 1 and 16"
                return None
            processed["write_priority"] = priority
        except (ValueError, TypeError):
            errors["write_priority"] = "Invalid priority value"
            return None
        
        # Parse options JSON if provided
        opts = processed.get("options", "")
        if isinstance(opts, dict):
            # Handle dict for select entity (value: label)
            opts_str = json.dumps(opts)  # or keep as dict if your schema_handler accepts it
        elif isinstance(opts, str):
            opts_str = opts.strip()
        else:
            opts_str = ""
        if opts_str:
            try:
                opts = json.loads(opts_str)
                if not isinstance(opts, dict):
                    errors["options"] = "Options must be a JSON object"
                    return None
                processed["options"] = opts
            except json.JSONDecodeError as err:
                errors["options"] = f"Invalid JSON: {err}"
                return None
        else:
            processed.pop("options", None)
        
        # Clean empty strings
        for field in ["format", "device_class", "state_class", "entity_category", "icon", "unit"]:
            value = processed.get(field)
            if value in ("", " ", None):
                processed.pop(field, None)
        
        # Ensure numeric fields have valid values
        try:
            processed["scale"] = float(processed.get("scale", 1.0))
            processed["offset"] = float(processed.get("offset", 0.0))
            processed["min"] = float(processed.get("min", 0.0))
            processed["max"] = float(processed.get("max", 100.0))
            processed["step"] = float(processed.get("step", 1.0))
        except (ValueError, TypeError):
            errors["scale"] = "Invalid numeric value"
            return None
        
        # Set required defaults
        processed.setdefault("data_type", "float")
        processed.setdefault("rw", "read")
        processed.setdefault("write_priority", 8)
        processed.setdefault("scale", 1.0)
        processed.setdefault("offset", 0.0)
        
        # Remove helper field (not stored)
        processed.pop("object_type_helper", None)
        
        return processed
    
    
    def get_defaults(self, entity):
        """Return entity dict with defaults for form display."""
        defaults = dict(entity)
        
        # Parse address to extract object type for helper field
        address = defaults.get("address", "")
        if address:
            parts = address.split(":")
            if len(parts) == 3:
                defaults["object_type_helper"] = parts[0]
        
        # Set empty string for optional fields
        defaults.setdefault("device_class", " ")
        defaults.setdefault("state_class", " ")
        defaults.setdefault("entity_category", " ")
        defaults.setdefault("icon", "")
        defaults.setdefault("unit", "")
        defaults.setdefault("format", "")
        
        # Ensure numeric fields have values
        defaults.setdefault("scale", 1.0)
        defaults.setdefault("offset", 0.0)
        defaults.setdefault("write_priority", 8)
        defaults.setdefault("min", 0.0)
        defaults.setdefault("max", 100.0)
        defaults.setdefault("step", 1.0)
        
        # Handle options
        opts = defaults.get("options")
        if isinstance(opts, dict):
            defaults["options"] = json.dumps(opts)
        else:
            defaults.setdefault("options", "")
        
        # Ensure required fields
        defaults.setdefault("data_type", "float")
        defaults.setdefault("rw", "read")
        
        return defaults
    
    
    def format_label(self, entity):
        """Format entity label for display."""
        name = entity.get("name", "Unknown")
        address = entity.get("address", "")
        
        # Parse address for better display
        if address:
            parts = address.split(":")
            if len(parts) == 3:
                # Show: "Name (objectType:instance)"
                return f"{name} ({parts[0]}:{parts[1]})"
        
        return f"{name} @ {address}"
    
    
    def merge_template(self, entities, template):
        """Merge template entities, processing each to add defaults."""
        added = 0
        existing = {(e.get("name"), e.get("address")) for e in entities}
        
        for template_entity in template:
            key = (template_entity.get("name"), template_entity.get("address"))
            if key not in existing:
                # Process template entity to add missing defaults
                errors = {}
                processed = self.process_input(template_entity, errors, existing=None)
                if processed and not errors:
                    entities.append(processed)
                    added += 1
                else:
                    _LOGGER.warning(
                        "Skipped invalid template entity: %s (errors: %s)",
                        template_entity.get("name"),
                        errors
                    )
        
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
                        options=["string", "integer", "counter32", "counter64", "gauge32", "float"],
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
            vol.Optional("device_class", default=defaults.get("device_class", " ")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[" ", "temperature", "power", "energy", "voltage", "current", "frequency", "duration"],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("state_class", default=defaults.get("state_class", " ")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[" ", "measurement", "total", "total_increasing"],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("entity_category", default=defaults.get("entity_category", " ")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[" ", "diagnostic", "config", "system"],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("icon", default=defaults.get("icon", "")): str,
            vol.Optional("unit", default=defaults.get("unit", "")): str,
            vol.Optional("scale", default=defaults.get("scale", 1.0)): vol.Coerce(float),
            vol.Optional("offset", default=defaults.get("offset", 0.0)): vol.Coerce(float),
            vol.Optional("format", default=defaults.get("format", "")): str,
            vol.Optional("options", default=defaults.get("options", "")): str,
        })

    

    @staticmethod
    def process_input(
        user_input: dict,
        errors: dict,
        existing: dict | None = None,
    ) -> dict | None:
        """
        Process user input for SNMP entity.
        Handles both new entities and edits, preserving old fields.
        """
        import json

        # Required validation - check for None/missing, not falsy (empty string is invalid for OID)
        if "address" not in user_input or not user_input.get("address"):
            errors["address"] = "required"
            return None

        # Start with existing data (for edits) or empty dict
        processed = dict(existing) if existing else {}

        # Update with new values, handling empty strings properly
        for key, value in user_input.items():
            if value in (" ", "", None):
                processed.pop(key, None)  # Clear if empty
            elif value is not None:
                processed[key] = value

        # Convert types
        try:
            processed["scale"] = float(processed.get("scale", 1.0))
            processed["offset"] = float(processed.get("offset", 0.0))
        except (ValueError, TypeError) as err:
            _LOGGER.error("Type conversion error: %s", err)
            errors["scale"] = "invalid_number"
            return None

        # Parse options JSON if provided
        options_raw = processed.get("options", "")
        if options_raw and isinstance(options_raw, str):
            try:
                parsed = json.loads(options_raw)
                if isinstance(parsed, dict):
                    # Normalize keys to strings
                    processed["options"] = {str(k): v for k, v in parsed.items()}
                else:
                    errors["options"] = "invalid_json"
                    return None
            except json.JSONDecodeError:
                errors["options"] = "invalid_json"
                return None
        elif not options_raw:
            processed.pop("options", None)

        # Ensure required fields exist with defaults
        processed.setdefault("data_type", "string")
        processed.setdefault("read_mode", "get")
        processed.setdefault("rw", "read")
        processed.setdefault("scale", 1.0)
        processed.setdefault("offset", 0.0)

        return processed

    def get_defaults(self, entity):
        """
        Get defaults for editing an entity.
        Returns the entity dict with all fields, using empty string for missing optional fields.
        """
        import json

        defaults = dict(entity)

        # Set empty string for optional fields that don't exist
        defaults.setdefault("device_class", " ")  # to ensure it work in dropdown
        defaults.setdefault("state_class", " ")
        defaults.setdefault("entity_category", " ")
        defaults.setdefault("icon", "")
        defaults.setdefault("format", "")
        defaults.setdefault("unit", "")

        # Ensure numeric fields have values
        defaults.setdefault("scale", 1.0)
        defaults.setdefault("offset", 0.0)

        # Ensure required fields
        defaults.setdefault("read_mode", "get")
        defaults.setdefault("data_type", "string")
        defaults.setdefault("rw", "read")

        # Convert options dict to JSON string for editing
        if "options" in defaults and isinstance(defaults["options"], dict):
            defaults["options"] = json.dumps(defaults["options"])
        else:
            defaults.setdefault("options", "")

        return defaults

    def format_label(self, entity):
        return f"{entity.get('name')} @ {entity.get('address')}"

    def merge_template(self, entities, template):
        """Merge template entities, processing each to add defaults."""
        added = 0
        existing = {(e.get("name"), e.get("address")) for e in entities}
        
        for template_entity in template:
            key = (template_entity.get("name"), template_entity.get("address"))
            if key not in existing:
                # Process template entity to add missing defaults
                errors = {}
                processed = self.process_input(template_entity, errors, existing=None)
                if processed and not errors:
                    entities.append(processed)
                    added += 1
                else:
                    _LOGGER.warning("Skipped invalid template entity: %s (errors: %s)", 
                                  template_entity.get("name"), errors)
        
        return added

class MQTTSchemaHandler:
    """Schema handler for MQTT entities."""
    
    config_key = CONF_ENTITIES  # MQTT uses 'entities' key
    
    def get_schema(self, defaults=None):
        """Return the schema for MQTT entity configuration."""
        defaults = defaults or {}
        return vol.Schema({
            vol.Required("name", default=defaults.get("name")): str,
            vol.Required("address", default=defaults.get("address")): str,  # MQTT topic
            vol.Required("data_type", default=defaults.get("data_type", "string")):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "string", "label": "String"},
                            {"value": "integer", "label": "Integer"},
                            {"value": "float", "label": "Float"},
                            {"value": "boolean", "label": "Boolean (on/off)"},
                            {"value": "json", "label": "JSON (structured data)"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            vol.Optional("rw", default=defaults.get("rw", "read")):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "read", "label": "Read (Subscribe)"},
                            {"value": "write", "label": "Write (Publish)"},
                            {"value": "rw", "label": "Read/Write"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            vol.Optional("qos", default=defaults.get("qos", 0)):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "0", "label": "QoS 0 (At most once)"},
                            {"value": "1", "label": "QoS 1 (At least once)"},
                            {"value": "2", "label": "QoS 2 (Exactly once)"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            vol.Optional("retain", default=defaults.get("retain", False)): bool,
            vol.Optional("scale", default=defaults.get("scale", 1.0)): vol.Coerce(float),
            vol.Optional("offset", default=defaults.get("offset", 0.0)): vol.Coerce(float),
            vol.Optional("format", default=defaults.get("format", "")): str,
            vol.Optional("options", default=defaults.get("options", "")): str,
            vol.Optional("device_class", default=defaults.get("device_class", "")): str,
            vol.Optional("state_class", default=defaults.get("state_class", "")): str,
            vol.Optional("entity_category", default=defaults.get("entity_category", "")): str,
            vol.Optional("icon", default=defaults.get("icon", "")): str,
            vol.Optional("unit", default=defaults.get("unit", "")): str,
        })
    
    def process_input(self, user_input, errors, existing=None):
        """Process and validate user input."""
        # Start with existing data (for edits) or empty dict
        processed = dict(existing) if existing else {}
        
        # Update with new values
        processed.update(user_input)
        
        # Validate topic format
        topic = processed.get("address", "")
        if not topic:
            errors["address"] = "Topic cannot be empty"
            return None
        
        # Validate QoS
        try:
            qos = int(processed.get("qos", 0))
            if qos not in (0, 1, 2):
                errors["qos"] = "QoS must be 0, 1, or 2"
                return None
            processed["qos"] = qos
        except (ValueError, TypeError):
            errors["qos"] = "Invalid QoS value"
            return None
        
        # Ensure boolean retain
        processed["retain"] = bool(processed.get("retain", False))
        
        # Parse options JSON if provided
        opts_str = processed.get("options", "")
        if isinstance(opts_str, str) and opts_str.strip():
            try:
                opts = json.loads(opts_str)
                processed["options"] = opts
            except json.JSONDecodeError:
                errors["options"] = "Invalid JSON format"
                return None
        elif isinstance(opts_str, dict):
            # Already a dict (from template)
            processed["options"] = opts_str
        else:
            processed.pop("options", None)
        
        # Clean empty strings
        for field in ["format", "device_class", "state_class", "entity_category", "icon", "unit"]:
            if not processed.get(field):
                processed.pop(field, None)
        
        # ADD REQUIRED DEFAULTS
        processed.setdefault("data_type", "string")
        processed.setdefault("rw", "read")
        processed.setdefault("qos", 0)
        processed.setdefault("retain", False)
        processed.setdefault("scale", 1.0)
        processed.setdefault("offset", 0.0)
        
        # Ensure numeric types
        try:
            processed["scale"] = float(processed.get("scale", 1.0))
            processed["offset"] = float(processed.get("offset", 0.0))
        except (ValueError, TypeError):
            errors["scale"] = "Invalid number"
            return None
        
        return processed
    
    def get_defaults(self, entity):
        """Return entity dict with defaults for form display."""
        defaults = dict(entity)
        
        # Set empty string for optional fields
        defaults.setdefault("device_class", "")
        defaults.setdefault("state_class", "")
        defaults.setdefault("entity_category", "")
        defaults.setdefault("icon", "")
        defaults.setdefault("unit", "")
        defaults.setdefault("format", "")
        
        # Ensure numeric fields
        defaults.setdefault("scale", 1.0)
        defaults.setdefault("offset", 0.0)
        defaults.setdefault("qos", 0)
        defaults.setdefault("retain", False)
        
        # Handle options
        opts = defaults.get("options")
        if isinstance(opts, dict):
            import json
            defaults["options"] = json.dumps(opts)
        else:
            defaults.setdefault("options", "")
        
        return defaults
    
    def format_label(self, entity):
        """Format entity label for display."""
        return f"{entity.get('name')} @ {entity.get('address')}"
    
    def merge_template(self, entities, template):
        """Merge template entities, processing each to add defaults."""
        added = 0
        existing = {(e.get("name"), e.get("address")) for e in entities}
        
        for template_entity in template:
            key = (template_entity.get("name"), template_entity.get("address"))
            if key not in existing:
                # Process template entity to add missing defaults
                errors = {}
                processed = self.process_input(template_entity, errors, existing=None)
                if processed and not errors:
                    entities.append(processed)
                    added += 1
                else:
                    _LOGGER.warning("Skipped invalid template entity: %s (errors: %s)", 
                                  template_entity.get("name"), errors)
        
        return added
