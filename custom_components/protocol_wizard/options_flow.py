#------------------------------------------
#-- base options_flow.py protocol wizard
#------------------------------------------
# options_flow.py

class ProtocolWizardOptionsFlow(config_entries.OptionsFlow):
    
    async def async_step_add_register(self, user_input=None):
        """Add register with protocol-specific fields."""
        
        protocol = self.config_entry.data["protocol"]
        
        if protocol == "modbus":
            schema = self._get_modbus_register_schema()
        elif protocol == "snmp":
            schema = self._get_snmp_register_schema()
        
        # ... rest of logic
    
    def _get_modbus_register_schema(self):
        """Modbus-specific register fields."""
        return vol.Schema({
            vol.Required("name"): str,
            vol.Required("address"): vol.All(vol.Coerce(int), vol.Range(min=0, max=65535)),
            vol.Required("data_type"): vol.In(["uint16", "int16", "float32", ...]),
            vol.Required("register_type"): vol.In(["holding", "input", "coil", ...]),
            # ... more Modbus fields
        })
    
    def _get_snmp_register_schema(self):
        """SNMP-specific register fields."""
        return vol.Schema({
            vol.Required("name"): str,
            vol.Required("address"): str,  # OID
            vol.Required("data_type"): vol.In(["string", "integer", "counter", "gauge"]),
            # ... more SNMP fields
        })
