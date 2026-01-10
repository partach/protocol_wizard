import { LitElement, html, css } from "https://unpkg.com/lit?module";

class ProtocolWizardCard extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      config: { type: Object },
      _selectedEntity: { type: String },
      _allEntities: { type: Array },
      _selectedStatus: { type: String },
      _writeStatus: { type: String },
      _protocol: { type: String },
      
      // Modbus properties
      _modbusAddress: { type: Number },
      _modbusSize: { type: Number },
      _modbusRegisterType: { type: String },
      _modbusDataType: { type: String },
      _modbusByteOrder: { type: String },
      _modbusWordOrder: { type: String },
      _modbusRawMode: { type: Boolean },
      
      // SNMP properties
      _snmpOid: { type: String },
      _snmpDataType: { type: String },
      
      // Shared
      _writeValue: { type: String },
      _showWriteWarning: { type: Boolean },
    };
  }

  constructor() {
    super();
    this._selectedEntity = "";
    this._allEntities = [];
    this._selectedStatus = "";
    this._writeStatus = "";
    
    // Modbus defaults
    this._modbusAddress = 0;
    this._modbusSize = 1;
    this._modbusRegisterType = "auto";
    this._modbusDataType = "uint16";
    this._modbusByteOrder = "big";
    this._modbusWordOrder = "big";
    this._modbusRawMode = false;
    
    // SNMP defaults
    this._snmpOid = "1.3.6.1.2.1.1.1.0";
    this._snmpDataType = "string";
    
    this._writeValue = "";
    this._showWriteWarning = false;
  }

  static getConfigElement() {
    return document.createElement("protocol_wizard-card-editor");
  }

  setConfig(config) {
    this.config = {
      advanced: true,
      ...config,
    };
  }

  getCardSize() {
    return 10;
  }

  updated(changedProps) {
    super.updated(changedProps);

    if (changedProps.has("hass") || changedProps.has("config")) {
        const protocol = this._getProtocol();
        if (protocol !== this._protocol) {
        this._protocol = protocol;
        }
        this._resolveDeviceEntities();
    }
  }

  _resolveDeviceEntities() {
    if (!this.hass) return;

    this._allEntities = [];
    const deviceId = this.config.device_id;
    const entityRegistry = this.hass.entities;
    const protocol = this._getProtocol();

    if (deviceId && entityRegistry) {
        // Step 1: Get all entities from this device
        const deviceEntities = Object.values(entityRegistry)
        .filter(e => e.device_id === deviceId)
        .map(e => e.entity_id)
        .sort();

        if (deviceEntities.length > 0) {
        // Step 2: Prefer the protocol-specific hub (e.g., snmp_hub or modbus_hub)
        const hubSuffix = `${protocol}_hub`;
        const protocolHub = deviceEntities.find(eid => eid.endsWith(hubSuffix));
        if (protocolHub) {
            this._allEntities = deviceEntities;
            this._selectedEntity = protocolHub;  // Auto-select the correct hub
            return;
        }

        // Step 3: If no exact hub, use all device entities (user can pick)
        this._allEntities = deviceEntities;

        // Auto-select first if none selected
        if (!this._selectedEntity || !this._allEntities.includes(this._selectedEntity)) {
            this._selectedEntity = this._allEntities[0];
        }
        return;
        }
    }

    // Fallback: Protocol-specific hubs from all protocol_wizard entities
    if (entityRegistry) {
        this._allEntities = Object.values(entityRegistry)
        .filter(e => e.platform === "protocol_wizard")
        .filter(e => e.entity_id.endsWith(`${this._protocol}_hub`))
        .map(e => e.entity_id)
        .sort();

        if (this._allEntities.length > 0) {
        this._selectedEntity = this._allEntities[0];
        return;
        }
    }

    // Final fallback: any protocol_wizard entity with suffix
    if (this._allEntities.length === 0) {
        this._allEntities = Object.keys(this.hass.states)
        .filter(eid => {
            const state = this.hass.states[eid];
            return state?.attributes?.platform === "protocol_wizard" &&
                eid.endsWith(`${this._protocol}_hub`);
        })
        .sort();

        if (this._allEntities.length > 0) {
        this._selectedEntity = this._allEntities[0];
        }
    }
  }

  _getTargetEntity() {
    const protocol = this._protocol;
    const hubSuffix = `${protocol}_hub`;

    const hub = this._allEntities.find(eid => eid.endsWith(hubSuffix));
    if (hub) return hub;

    return this._allEntities[0] ?? null;
  }

  _handleModbusDataTypeChange(e) {
    this._modbusDataType = e.target.value;
    const sizes = {
      "uint16": 1, "int16": 1,
      "uint32": 2, "int32": 2,
      "float32": 2,
      "uint64": 4, "int64": 4,
      "string": 1,
    };
    this._modbusSize = sizes[this._modbusDataType] || 1;
    this.requestUpdate();
  }

  _parseWriteValue() {
    if (!this._writeValue) return 0;
    
    const val = this._writeValue.trim().toLowerCase();
    if (val === "true" || val === "1" || val === "on") return true;
    if (val === "false" || val === "0" || val === "off") return false;
    
    const num = Number(this._writeValue);
    if (!isNaN(num)) return num;
    
    return this._writeValue;
  }

  async _sendRead() {
    const targetEntity = this._getTargetEntity();
    if (!targetEntity) {
      this._selectedStatus = "No hub available";
      this.requestUpdate();
      return;
    }

    this._selectedStatus = "Reading...";
    this.requestUpdate();

    try {
      if (this._protocol === "modbus") {
        await this._sendModbusRead(targetEntity);
      } else if (this._protocol === "snmp") {
        await this._sendSnmpRead(targetEntity);
      }
    } catch (err) {
      console.error("Read error:", err);
      this._selectedStatus = `Read failed: ${err.message || err}`;
      this.requestUpdate();
    }
  }

  async _sendModbusRead(targetEntity) {
    if (this._modbusAddress === undefined) {
      this._selectedStatus = "Missing address";
      this.requestUpdate();
      return;
    }

    const result = await this.hass.callWS({
      type: "call_service",
      domain: "protocol_wizard",
      service: "read_register",
      service_data: {
        entity_id: targetEntity,
        device_id: this.config.device_id,
        address: Number(this._modbusAddress),
        register_type: this._modbusRegisterType || "auto",
        data_type: this._modbusDataType || "uint16",
        size: Number(this._modbusSize),
        byte_order: this._modbusByteOrder || "big",
        word_order: this._modbusWordOrder || "big",
        raw: this._modbusRawMode,
      },
      return_response: true,
    });

    let displayValue = "";
    let rawData = null;
    
    if (result?.value !== undefined && typeof result.value === "object") {
      rawData = result.value;
    } else if (result?.response?.value !== undefined && typeof result.response.value === "object") {
      rawData = result.response.value;
    }

    if (this._modbusRawMode && rawData) {
      const registers = rawData.registers || [];
      const bits = rawData.bits || [];
      const hex = registers.map(r => `0x${r.toString(16).toUpperCase().padStart(4, '0')}`).join(' ');
      
      let ascii = '';
      try {
        const bytes = new Uint8Array(registers.flatMap(r => [r >> 8, r & 0xFF]));
        ascii = new TextDecoder('ascii', { fatal: false }).decode(bytes).replace(/\0/g, '').trim();
        if (ascii === '') ascii = '(no printable ASCII)';
      } catch {
        ascii = '(invalid ASCII)';
      }

      const binary = registers.map(r => r.toString(2).padStart(16, '0')).join(' ');
      const bitsView = bits.length > 0 ? `Bits: [${bits.map(b => b ? 1 : 0).join(', ')}]` : '';

      displayValue = `HEX: ${hex}\nASCII: ${ascii}\nBinary: ${binary}`;
      if (bitsView) displayValue += `\n${bitsView}`;
      if (rawData.detected_type) displayValue += `\nType: ${rawData.detected_type}`;
    } else {
      const value = result?.value ?? result?.response?.value ?? null;
      displayValue = value !== null ? String(value) : "No value";
    }

    this._writeValue = displayValue;
    this._selectedStatus = "Read OK";
    this.requestUpdate();
  }

  async _sendSnmpRead(targetEntity) {
    if (!this._snmpOid) {
      this._selectedStatus = "Missing OID";
      this.requestUpdate();
      return;
    }

    const result = await this.hass.callWS({
      type: "call_service",
      domain: "protocol_wizard",
      service: "read_snmp",
      service_data: {
        entity_id: targetEntity,
        device_id: this.config.device_id,
        oid: this._snmpOid,
        data_type: this._snmpDataType,
      },
      return_response: true,
    });

    const value = result?.value ?? result?.response?.value ?? null;
    this._writeValue = value !== null ? String(value) : "No value";
    this._selectedStatus = "Read OK";
    this.requestUpdate();
  }

  async _sendWrite() {
    const targetEntity = this._getTargetEntity();
    if (!targetEntity) {
      this._writeStatus = "No hub available";
      this.requestUpdate();
      return;
    }

    if (this._protocol === "modbus" && this._modbusRegisterType === "auto") {
        this._writeStatus = "Can't write with Auto, select Holding or Coil";
        this._showWriteWarning = true;
        this.requestUpdate();
        return;
    }

    if (this._writeValue === undefined) {
      this._writeStatus = "Missing value";
      this.requestUpdate();
      return;
    }

    this._writeStatus = "Writing...";
    this.requestUpdate();

    try {
      if (this._protocol === "modbus") {
        await this._sendModbusWrite(targetEntity);
      } else if (this._protocol === "snmp") {
        await this._sendSnmpWrite(targetEntity);
      }
    } catch (err) {
      console.error("Write error:", err);
      this._writeStatus = `Write failed: ${err.message || err}`;
      this.requestUpdate();
    }
  }

  async _sendModbusWrite(targetEntity) {
    if (this._modbusAddress === undefined) {
      this._writeStatus = "Missing address";
      this.requestUpdate();
      return;
    }

    await this.hass.callWS({
      type: "call_service",
      domain: "protocol_wizard",
      service: "write_register",
      service_data: {
        entity_id: targetEntity,
        device_id: this.config.device_id,
        address: Number(this._modbusAddress),
        register_type: this._modbusRegisterType || "auto",
        data_type: this._modbusDataType || "uint16",
        byte_order: this._modbusByteOrder || "big",
        word_order: this._modbusWordOrder || "big",
        value: this._parseWriteValue(),
      },
    });

    this._writeStatus = "Write OK";
    this.requestUpdate();
  }

  _getProtocol() {
    const deviceId = this.config.device_id;
    if (!deviceId || !this.hass?.entities) return "unknown";

    const entities = Object.values(this.hass.entities)
        .filter(e => e.device_id === deviceId)
        .map(e => e.entity_id);

    if (entities.some(eid => eid.endsWith("_modbus_hub"))) return "modbus";
    if (entities.some(eid => eid.endsWith("_snmp_hub"))) return "snmp";

    return "unknown";
  }

  async _sendSnmpWrite(targetEntity) {
    if (!this._snmpOid) {
      this._writeStatus = "Missing OID";
      this.requestUpdate();
      return;
    }

    await this.hass.callWS({
      type: "call_service",
      domain: "protocol_wizard",
      service: "write_snmp",
      service_data: {
        entity_id: targetEntity,
        device_id: this.config.device_id,
        oid: this._snmpOid,
        value: this._parseWriteValue(),
        data_type: this._snmpDataType,
      },
    });

    this._writeStatus = "Write OK";
    this.requestUpdate();
  }
  
  _renderModbusFields() {
    return html`
      <div class="field-row">
        <span class="label">Register Address:</span>
        <input
          type="number"
          placeholder="e.g. 100"
          min="0"
          max="65535"
          .value=${this._modbusAddress}
          @input=${e => this._modbusAddress = Number(e.target.value)}
        />
      </div>

      <div class="field-row">
        <span class="label">Register Category:</span>
        <select .value=${this._modbusRegisterType} @change=${e => this._modbusRegisterType = e.target.value}>
          <option value="auto">Auto-detect</option>
          <option value="holding">Holding Register (Read/Write)</option>
          <option value="input">Input Register (Read Only)</option>
          <option value="coil">Coil (Digital Out)</option>
          <option value="discrete">Discrete Input (Digital In)</option>
        </select>
      </div>

      <div class="field-row">
        <span class="label">Data Format:</span>
        <select .value=${this._modbusDataType} @change=${this._handleModbusDataTypeChange}>
          <option value="uint16">16-bit Unsigned (uint16)</option>
          <option value="int16">16-bit Signed (int16)</option>
          <option value="uint32">32-bit Unsigned (uint32)</option>
          <option value="int32">32-bit Signed (int32)</option>
          <option value="float32">32-bit Float (float32)</option>
          <option value="uint64">64-bit Unsigned (uint64)</option>
          <option value="int64">64-bit Signed (int64)</option>
          <option value="string">Character String</option>
        </select>
      </div>

      <div class="field-row">
        <span class="label">Register Count (Size):</span>
        <input
          type="number"
          placeholder="1"
          min="1"
          max="20"
          .value=${this._modbusSize}
          @input=${e => this._modbusSize = Number(e.target.value)}
        />
      </div>

      <div class="field-row">
        <span class="label">Endianness (Byte):</span>
        <select .value=${this._modbusByteOrder} @change=${e => this._modbusByteOrder = e.target.value}>
          <option value="big">Big Endian (ABCD)</option>
          <option value="little">Little Endian (DCBA)</option>
        </select>
      </div>

      <div class="field-row">
        <span class="label">Endianness (Word):</span>
        <select .value=${this._modbusWordOrder} @change=${e => this._modbusWordOrder = e.target.value}>
          <option value="big">Big Word (Most Significant First)</option>
          <option value="little">Little Word (Least Significant First)</option>
        </select>
      </div>

      <div class="field-row checkbox-row">
        <span class="label">Bypass Processing:</span>
        <label>
          <input type="checkbox" @change=${e => this._modbusRawMode = e.target.checked} ?checked=${this._modbusRawMode} />
          Enable Raw Mode
        </label>
      </div>
    `;
  }

  _renderSnmpFields() {
    return html`
      <div class="field-row">
        <span class="label">OID:</span>
        <input
          type="text"
          placeholder="e.g. 1.3.6.1.2.1.1.1.0"
          .value=${this._snmpOid}
          @input=${e => this._snmpOid = e.target.value}
        />
      </div>

      <div class="field-row">
        <span class="label">Data Type:</span>
        <select .value=${this._snmpDataType} @change=${e => this._snmpDataType = e.target.value}>
          <option value="string">OctetString</option>
          <option value="integer32">Integer32</option>
          <option value="counter32">Counter32</option>
          <option value="counter64">Counter64</option>
          <option value="gauge32">Gauge32</option>
          <option value="timeticks">TimeTicks</option>
          <option value="ipaddress">IP Address</option>
          <option value="objectIdentifier">ObjectIdentifier</option>
        </select>
      </div>
    `;
  }

  render() {
    if (!this.hass || !this.config) return html``;

    const protocol = this._getProtocol();

    return html`
        <ha-card>
        ${this.config.name ? html`
            <div class="header">${this.config.name}</div>
        ` : ""}

        <div class="section">
          <div class="section-title">Protocol Wizard</div>

          <div class="write-section">
            <!-- Device Info with detected protocol -->
            <div class="info">
                Device: ${this.hass.devices?.[this.config.device_id]?.name || "Unknown"}
                &nbsp |  Protocol: ${protocol.toUpperCase()}
                <br>
                Hub entity: ${this._getTargetEntity() || "Not found"}
            </div>

            <!-- Protocol-specific fields -->
            ${protocol === "modbus" ? this._renderModbusFields() : this._renderSnmpFields()}

            <!-- Value field -->
            <input
              type="text"
              placeholder="Value"
              .value=${this._writeValue || ""}
              @input=${e => this._writeValue = e.target.value}
            />

            <!-- Action buttons -->
            <div class="button-row">
              <button @click=${this._sendRead}>Read</button>
              <button @click=${this._sendWrite}>Write</button>
            </div>

            <!-- Status messages -->
            ${this._selectedStatus ? html`
              <div class="status">${this._selectedStatus}</div>
            ` : ""}
            
            ${this._writeStatus ? html`
              <div class="status">${this._writeStatus}</div>
            ` : ""}
          </div>
        </div>
      </ha-card>
    `;
  }

  static get styles() {
    return css`
      ha-card {
        padding: 16px;
      }
      .header {
        font-size: 1.4em;
        font-weight: bold;
        margin-bottom: 16px;
        text-align: center;
      }
      .section-title {
        font-size: 1.2em;
        font-weight: bold;
        margin-bottom: 12px;
      }
      .write-section {
        display: grid;
        grid-template-columns: 1fr;
        gap: 12px;
      }
      select, input {
        padding: 8px;
        border-radius: 4px;
        border: 1px solid var(--divider-color);
        background: var(--card-background-color);
        color: var(--primary-text-color);
      }
      label {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .button-row {
        display: flex;
        gap: 12px;
      }
      .info {
        padding: 8px;
        background: var(--secondary-background-color);
        border-radius: 4px;
        font-size: 0.9em;
        color: var(--secondary-text-color);
        margin-bottom: 12px;
      }
      button {
        flex: 1;
        background: var(--primary-color);
        color: var(--text-primary-color);
        border: none;
        padding: 10px 20px;
        border-radius: 4px;
        cursor: pointer;
        font-weight: bold;
      }
      button:hover {
        opacity: 0.9;
      }
      .status {
        text-align: center;
        font-weight: bold;
        color: var(--primary-color);
        padding: 8px;
        background: var(--secondary-background-color);
        border-radius: 4px;
      }
      .field-row {
        display: flex;
        align-items: center;
        margin-bottom: 8px;
      }
      .label {
        width: 160px;
        font-weight: bold;
        font-size: 0.9em;
        color: var(--primary-text-color);
      }
      input, select {
        flex: 1;
        padding: 4px;
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        background: var(--card-background-color);
        color: var(--primary-text-color);
      }
      .checkbox-row label {
        display: flex;
        align-items: center;
        cursor: pointer;
      }
    `;
  }
}

class ProtocolWizardCardEditor extends LitElement {
  static get properties() {
    return {
      hass: {},
      _config: {},
    };
  }

  setConfig(config) {
    this._config = { ...config };
  }

  render() {
    if (!this.hass) return html``;

    return html`
      <ha-form
        .hass=${this.hass}
        .data=${this._config}
        .schema=${this._schema()}
        @value-changed=${this._valueChanged}
      ></ha-form>
    `;
  }

  _schema() {
    return [
      {
        name: "name",
        selector: { text: {} },
      },
      {
        name: "device_id",
        selector: {
          device: {
            integration: "protocol_wizard",
          },
        },
      },
    ];
  }

  _valueChanged(ev) {
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config: ev.detail.value },
        bubbles: true,
        composed: true,
      })
    );
  }
}

customElements.define("protocol_wizard-card", ProtocolWizardCard);
customElements.define("protocol_wizard-card-editor", ProtocolWizardCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "protocol_wizard-card",
  name: "Protocol Wizard Card",
  description: "Multi-protocol device manipulation (Modbus, SNMP)",
  preview: true,
});
