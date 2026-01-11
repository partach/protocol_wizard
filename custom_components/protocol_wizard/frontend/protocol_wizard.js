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
      
      // Entity creation
      _lastReadSuccess: { type: Boolean },
      _lastReadData: { type: Object },
      _showEntityForm: { type: Boolean },
      _newEntityName: { type: String },
      _newEntityRW: { type: String },
      _newEntityScale: { type: Number },
      _newEntityOffset: { type: Number },
      _newEntityOptions: { type: String },
      _newEntityFormat: { type: String },
      _newEntityIcon: { type: String },
      _createEntityStatus: { type: String },
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
    
    // Entity creation defaults
    this._lastReadSuccess = false;
    this._lastReadData = null;
    this._showEntityForm = false;
    this._newEntityName = "";
    this._newEntityRW = "read";
    this._newEntityScale = 1.0;
    this._newEntityOffset = 0.0;
    this._newEntityOptions = "";
    this._newEntityFormat = "";
    this._newEntityIcon = "";
    this._createEntityStatus = "";
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
        const deviceEntities = Object.values(entityRegistry)
        .filter(e => e.device_id === deviceId)
        .map(e => e.entity_id)
        .sort();

        if (deviceEntities.length > 0) {
        const hubSuffix = `${protocol}_hub`;
        const protocolHub = deviceEntities.find(eid => eid.endsWith(hubSuffix));
        if (protocolHub) {
            this._allEntities = deviceEntities;
            this._selectedEntity = protocolHub;
            return;
        }

        this._allEntities = deviceEntities;
        this._selectedEntity = deviceEntities[0];
        }
    }
  }

  _getTargetEntity() {
    if (this._selectedEntity) return this._selectedEntity;
    if (this._allEntities.length > 0) return this._allEntities[0];
    return null;
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

  _handleModbusDataTypeChange(e) {
    this._modbusDataType = e.target.value;
    
    const sizeMap = {
      uint16: 1,
      int16: 1,
      uint32: 2,
      int32: 2,
      float32: 2,
      uint64: 4,
      int64: 4,
      string: 4,
    };
    
    this._modbusSize = sizeMap[this._modbusDataType] || 1;
    this.requestUpdate();
  }

  _parseWriteValue() {
    const val = this._writeValue?.trim();
    if (!val) return null;
    if (!isNaN(val)) return Number(val);
    return val;
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

  async _sendRead() {
    const targetEntity = this._getTargetEntity();
    if (!targetEntity) {
      this._selectedStatus = "No hub available";
      this._lastReadSuccess = false;
      this.requestUpdate();
      return;
    }

    this._selectedStatus = "Reading...";
    this._lastReadSuccess = false;
    this._showEntityForm = false;
    this.requestUpdate();

    try {
      if (this._protocol === "modbus") {
        await this._sendModbusRead(targetEntity);
      } else if (this._protocol === "snmp") {
        await this._sendSnmpRead(targetEntity);
      }
      this._lastReadSuccess = true;
    } catch (err) {
      console.error("Read error:", err);
      this._selectedStatus = `Read failed: ${err.message || err}`;
      this._lastReadSuccess = false;
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

    // Store read data for entity creation and table display
    this._lastReadData = {
      address: this._modbusAddress,
      register_type: this._modbusRegisterType === "auto" 
        ? (result?.detected_type || "holding") 
        : this._modbusRegisterType,
      data_type: this._modbusDataType,
      size: this._modbusSize,
      byte_order: this._modbusByteOrder,
      word_order: this._modbusWordOrder,
      value: result?.value ?? result?.response?.value ?? null,
      raw: result?.value ?? result?.response?.value ?? null,  // Store for table
    };

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
      
      // Store parsed data for table
      this._lastReadData.table = {
        hex: hex,
        ascii: ascii,
        binary: binary,
        bits: bitsView,
        detected_type: rawData.detected_type,
      };
    } else {
      const value = result?.value ?? result?.response?.value ?? null;
      displayValue = value !== null ? String(value) : "No value";
      
      // Store for table
      this._lastReadData.table = {
        value: displayValue,
      };
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
    
    // Store read data for entity creation and table display
    this._lastReadData = {
      address: this._snmpOid,
      data_type: this._snmpDataType,
      value: value,
      table: {
        value: value !== null ? String(value) : "No value",
      },
    };
    
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

  _showCreateEntityForm() {
    this._showEntityForm = true;
    this._createEntityStatus = "";
    
    // Pre-fill entity name based on protocol
    if (this._protocol === "modbus") {
      const regType = this._lastReadData?.register_type || "register";
      this._newEntityName = `${regType}_${this._lastReadData?.address || 0}`;
    } else if (this._protocol === "snmp") {
      const oidParts = (this._lastReadData?.address || "").split(".");
      const lastPart = oidParts[oidParts.length - 1] || "unknown";
      this._newEntityName = `snmp_oid_${lastPart}`;
    }
    
    this.requestUpdate();
  }

  _cancelCreateEntity() {
    this._showEntityForm = false;
    this._newEntityName = "";
    this._newEntityRW = "read";
    this._newEntityScale = 1.0;
    this._newEntityOffset = 0.0;
    this._newEntityOptions = "";
    this._newEntityFormat = "";
    this._newEntityIcon = "";
    this._createEntityStatus = "";
    this.requestUpdate();
  }

  async _createEntity() {
    if (!this._newEntityName || !this._lastReadData) {
      this._createEntityStatus = "Missing entity name or read data";
      this.requestUpdate();
      return;
    }

    this._createEntityStatus = "Creating entity...";
    this.requestUpdate();

    try {
      const targetEntity = this._getTargetEntity();
      if (!targetEntity) {
        throw new Error("No hub entity found");
      }

      // Build service data based on protocol
      let serviceData = {
        entity_id: targetEntity,  // This becomes the target
        name: this._newEntityName,
        address: String(this._lastReadData.address),
        rw: this._newEntityRW || "read",
        scale: this._newEntityScale !== undefined ? this._newEntityScale : 1.0,
        offset: this._newEntityOffset !== undefined ? this._newEntityOffset : 0.0,
      };
      
      // Add optional fields if provided
      if (this._newEntityOptions && this._newEntityOptions.trim()) {
        serviceData.options = this._newEntityOptions.trim();
      }
      if (this._newEntityFormat && this._newEntityFormat.trim()) {
        serviceData.format = this._newEntityFormat.trim();
      }
      if (this._newEntityIcon && this._newEntityIcon.trim()) {
        serviceData.icon = this._newEntityIcon.trim();
      }
      
      if (this._protocol === "modbus") {
        serviceData = {
          ...serviceData,
          register_type: this._lastReadData.register_type,
          data_type: this._lastReadData.data_type,
          size: this._lastReadData.size,
          byte_order: this._lastReadData.byte_order,
          word_order: this._lastReadData.word_order,
        };
      } else if (this._protocol === "snmp") {
        serviceData = {
          ...serviceData,
          data_type: this._lastReadData.data_type,
          read_mode: "get",
        };
      }

      // Call the add_entity service
      const result = await this.hass.callService(
        "protocol_wizard",
        "add_entity",
        serviceData
      );

      this._createEntityStatus = "Entity created successfully!";
      this._showEntityForm = false;
      
      // Reset form after 3 seconds
      setTimeout(() => {
        this._createEntityStatus = "";
        this._lastReadSuccess = false;
        this.requestUpdate();
      }, 3000);

      this.requestUpdate();
    } catch (err) {
      console.error("Create entity error:", err);
      this._createEntityStatus = `Failed: ${err.message || err}`;
      this.requestUpdate();
    }
  }

  _copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
      // Show brief confirmation
      const originalStatus = this._selectedStatus;
      this._selectedStatus = "Copied to clipboard!";
      this.requestUpdate();
      setTimeout(() => {
        this._selectedStatus = originalStatus;
        this.requestUpdate();
      }, 1500);
    }).catch(err => {
      console.error('Failed to copy:', err);
      this._selectedStatus = "Copy failed";
      this.requestUpdate();
    });
  }

  _renderResultsTable() {
    if (!this._lastReadSuccess || !this._lastReadData?.table) {
      return html``;
    }

    const table = this._lastReadData.table;
    
    if (this._modbusRawMode && this._protocol === "modbus") {
      // Raw mode table
      return html`
        <div class="results-table">
          <div class="table-title">Read Results</div>
          <table>
            <tbody>
              ${table.hex ? html`
                <tr>
                  <td class="label-cell">HEX</td>
                  <td class="value-cell">${table.hex}</td>
                  <td class="copy-cell">
                    <button class="copy-btn" @click=${() => this._copyToClipboard(table.hex)} title="Copy HEX">
                      Copy
                    </button>
                  </td>
                </tr>
              ` : ''}
              ${table.ascii ? html`
                <tr>
                  <td class="label-cell">ASCII</td>
                  <td class="value-cell">${table.ascii}</td>
                  <td class="copy-cell">
                    <button class="copy-btn" @click=${() => this._copyToClipboard(table.ascii)} title="Copy ASCII">
                      Copy
                    </button>
                  </td>
                </tr>
              ` : ''}
              ${table.binary ? html`
                <tr>
                  <td class="label-cell">Binary</td>
                  <td class="value-cell">${table.binary}</td>
                  <td class="copy-cell">
                    <button class="copy-btn" @click=${() => this._copyToClipboard(table.binary)} title="Copy Binary">
                      Copy
                    </button>
                  </td>
                </tr>
              ` : ''}
              ${table.bits ? html`
                <tr>
                  <td class="label-cell">Bits</td>
                  <td class="value-cell">${table.bits}</td>
                  <td class="copy-cell">
                    <button class="copy-btn" @click=${() => this._copyToClipboard(table.bits)} title="Copy Bits">
                      Copy
                    </button>
                  </td>
                </tr>
              ` : ''}
              ${table.detected_type ? html`
                <tr>
                  <td class="label-cell">Detected Type</td>
                  <td class="value-cell">${table.detected_type}</td>
                  <td class="copy-cell">
                    <button class="copy-btn" @click=${() => this._copyToClipboard(table.detected_type)} title="Copy Type">
                      Copy
                    </button>
                  </td>
                </tr>
              ` : ''}
            </tbody>
          </table>
        </div>
      `;
    } else {
      // Simple value table
      return html`
        <div class="results-table">
          <div class="table-title">Read Results</div>
          <table>
            <tbody>
              <tr>
                <td class="label-cell">Value</td>
                <td class="value-cell">${table.value}</td>
                <td class="copy-cell">
                  <button class="copy-btn" @click=${() => this._copyToClipboard(table.value)} title="Copy Value">
                    Copy
                  </button>
                </td>
              </tr>
              <tr>
                <td class="label-cell">Address</td>
                <td class="value-cell">${this._lastReadData.address}</td>
                <td class="copy-cell">
                  <button class="copy-btn" @click=${() => this._copyToClipboard(String(this._lastReadData.address))} title="Copy Address">
                    Copy
                  </button>
                </td>
              </tr>
              ${this._protocol === "modbus" ? html`
                <tr>
                  <td class="label-cell">Type</td>
                  <td class="value-cell">${this._lastReadData.register_type}</td>
                  <td class="copy-cell">
                    <button class="copy-btn" @click=${() => this._copyToClipboard(this._lastReadData.register_type)} title="Copy Type">
                      Copy
                    </button>
                  </td>
                </tr>
              ` : ''}
            </tbody>
          </table>
        </div>
      `;
    }
  }

  _renderCreateEntityButton() {
    if (!this._lastReadSuccess || this._showEntityForm) {
      return html``;
    }

    return html`
      <div class="create-entity-section">
        <button class="create-entity-btn" @click=${this._showCreateEntityForm}>
          + Create Entity from this Read
        </button>
      </div>
    `;
  }

  _renderCreateEntityForm() {
    if (!this._showEntityForm) {
      return html``;
    }

    return html`
      <div class="entity-form">
        <div class="form-title">Create New Entity</div>
        
        <div class="field-row">
          <span class="label">Entity Name:</span>
          <input
            type="text"
            placeholder="Enter entity name"
            .value=${this._newEntityName}
            @input=${e => this._newEntityName = e.target.value}
          />
        </div>

        <div class="field-row">
          <span class="label">Read/Write Mode:</span>
          <select .value=${this._newEntityRW || "read"} @change=${e => this._newEntityRW = e.target.value}>
            <option value="read">Read Only</option>
            <option value="write">Write Only</option>
            <option value="rw">Read/Write</option>
          </select>
        </div>

        <div class="form-section-title">Value Processing</div>

        <div class="field-row">
          <span class="label">Scale Factor:</span>
          <input
            type="number"
            step="0.01"
            placeholder="1.0"
            .value=${this._newEntityScale !== undefined ? this._newEntityScale : 1.0}
            @input=${e => this._newEntityScale = Number(e.target.value)}
          />
        </div>
        <div class="field-help">Multiply raw value by this factor</div>

        <div class="field-row">
          <span class="label">Offset:</span>
          <input
            type="number"
            step="0.01"
            placeholder="0.0"
            .value=${this._newEntityOffset !== undefined ? this._newEntityOffset : 0.0}
            @input=${e => this._newEntityOffset = Number(e.target.value)}
          />
        </div>
        <div class="field-help">Add this value after scaling</div>

        <div class="form-section-title">Display Options</div>

        <div class="field-row">
          <span class="label">Options (JSON):</span>
          <input
            type="text"
            placeholder='{"0": "Off", "1": "On"}'
            .value=${this._newEntityOptions || ""}
            @input=${e => this._newEntityOptions = e.target.value}
          />
        </div>
        <div class="field-help">For select entities: map values to labels</div>

        <div class="field-row">
          <span class="label">Format String:</span>
          <input
            type="text"
            placeholder="{d} days {h} hours"
            .value=${this._newEntityFormat || ""}
            @input=${e => this._newEntityFormat = e.target.value}
          />
        </div>
        <div class="field-help">Custom display format (e.g., temperature, time)</div>

        <div class="field-row">
          <span class="label">Icon:</span>
          <input
            type="text"
            placeholder="mdi:thermometer"
            .value=${this._newEntityIcon || ""}
            @input=${e => this._newEntityIcon = e.target.value}
          />
        </div>
        <div class="field-help">Material Design Icon name</div>

        <div class="read-summary">
          <strong>Configuration from last read:</strong><br>
          ${this._protocol === "modbus" ? html`
            Address: ${this._lastReadData?.address}<br>
            Type: ${this._lastReadData?.register_type}<br>
            Data Type: ${this._lastReadData?.data_type}<br>
            Size: ${this._lastReadData?.size}<br>
          ` : html`
            OID: ${this._lastReadData?.address}<br>
            Data Type: ${this._lastReadData?.data_type}<br>
          `}
          Value: ${this._lastReadData?.value}
        </div>

        <div class="button-row">
          <button @click=${this._createEntity}>Create Entity</button>
          <button class="cancel-btn" @click=${this._cancelCreateEntity}>Cancel</button>
        </div>

        ${this._createEntityStatus ? html`
          <div class="status ${this._createEntityStatus.includes('successfully') ? 'success' : ''}">${this._createEntityStatus}</div>
        ` : ""}
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
                &nbsp; | &nbsp; Protocol: ${protocol.toUpperCase()}
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

            <!-- Results Table (shown after successful read) -->
            ${this._renderResultsTable()}

            <!-- Create Entity Button (shown after successful read) -->
            ${this._renderCreateEntityButton()}

            <!-- Create Entity Form -->
            ${this._renderCreateEntityForm()}
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
      button.cancel-btn {
        background: var(--secondary-text-color);
      }
      .status {
        text-align: center;
        font-weight: bold;
        color: var(--primary-color);
        padding: 8px;
        background: var(--secondary-background-color);
        border-radius: 4px;
      }
      .status.success {
        color: var(--success-color, #4caf50);
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
      
      /* Results Table Styles */
      .results-table {
        margin-top: 16px;
        padding: 12px;
        background: var(--card-background-color);
        border-radius: 4px;
        border: 1px solid var(--divider-color);
      }
      .table-title {
        font-weight: bold;
        margin-bottom: 8px;
        color: var(--primary-text-color);
      }
      .results-table table {
        width: 100%;
        border-collapse: collapse;
      }
      .results-table tr {
        border-bottom: 1px solid var(--divider-color);
      }
      .results-table tr:last-child {
        border-bottom: none;
      }
      .results-table td {
        padding: 8px 4px;
      }
      .label-cell {
        font-weight: bold;
        width: 120px;
        color: var(--secondary-text-color);
      }
      .value-cell {
        font-family: monospace;
        word-break: break-all;
        color: var(--primary-text-color);
      }
      .copy-cell {
        width: 60px;
        text-align: right;
      }
      .copy-btn {
        background: var(--secondary-background-color);
        color: var(--primary-text-color);
        border: 1px solid var(--divider-color);
        padding: 4px 8px;
        border-radius: 4px;
        cursor: pointer;
        font-size: 12px;
        min-width: auto;
        flex: none;
      }
      .copy-btn:hover {
        background: var(--primary-color);
        color: var(--text-primary-color);
      }
      
      /* Create Entity Styles */
      .create-entity-section {
        margin-top: 12px;
        padding-top: 12px;
        border-top: 1px solid var(--divider-color);
      }
      .create-entity-btn {
        width: 100%;
        background: var(--success-color, #4caf50);
        color: white;
      }
      .entity-form {
        margin-top: 12px;
        padding: 16px;
        background: var(--secondary-background-color);
        border-radius: 8px;
        border: 2px solid var(--primary-color);
      }
      .form-title {
        font-size: 1.1em;
        font-weight: bold;
        margin-bottom: 12px;
        color: var(--primary-text-color);
      }
      .form-section-title {
        font-size: 0.95em;
        font-weight: bold;
        margin-top: 16px;
        margin-bottom: 8px;
        color: var(--primary-color);
        border-bottom: 1px solid var(--divider-color);
        padding-bottom: 4px;
      }
      .field-help {
        font-size: 0.85em;
        color: var(--secondary-text-color);
        margin-top: -8px;
        margin-bottom: 8px;
        margin-left: 160px;
        font-style: italic;
      }
      .read-summary {
        padding: 12px;
        background: var(--card-background-color);
        border-radius: 4px;
        margin: 12px 0;
        font-size: 0.9em;
        line-height: 1.6;
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
