#------------------------------------------
#-- base config_flow.py protocol wizard
#------------------------------------------
# config_flow.py

class ProtocolWizardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    
    async def async_step_user(self, user_input=None):
        """Step 1: Select protocol."""
        if user_input is not None:
            self.protocol = user_input["protocol"]
            return await self.async_step_connection()
        
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("protocol"): vol.In(
                    ProtocolRegistry.available_protocols()
                )
            })
        )
    
    async def async_step_connection(self, user_input=None):
        """Step 2: Protocol-specific connection config."""
        
        if self.protocol == "modbus":
            return await self.async_step_modbus_connection(user_input)
        elif self.protocol == "snmp":
            return await self.async_step_snmp_connection(user_input)
        # ... more protocols
    
    async def async_step_modbus_connection(self, user_input=None):
        """Modbus-specific connection settings."""
        # Your existing Modbus config flow
        pass
    
    async def async_step_snmp_connection(self, user_input=None):
        """SNMP-specific connection settings."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"SNMP {user_input['host']}",
                data={
                    "protocol": "snmp",
                    "host": user_input["host"],
                    "community": user_input["community"],
                    "version": user_input["version"],
                }
            )
        
        return self.async_show_form(
            step_id="snmp_connection",
            data_schema=vol.Schema({
                vol.Required("host"): str,
                vol.Required("community", default="public"): str,
                vol.Required("version", default="2c"): vol.In(["1", "2c", "3"]),
            })
        )
