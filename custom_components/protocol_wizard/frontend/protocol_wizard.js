import { LitElement, html, css } from "https://unpkg.com/lit?module";

class ProtocolWizardCard extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      config: { type: Object },
      _selectedEntity: { type: String },
      _allEntities: { type: Array },
      _status: { type: String },
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
      _snmpWalkMode: { type: Boolean },
      
      // Shared
      _writeValue: { type: String },
      _viewMode: { type: String }, // 'text' or 'table'
      _tableData: { type: Array },
      
      // Entity creation (NEW)
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
    this._status = "";
    
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
    this._snmpWalkMode = false;
    
    this._writeValue = "";
    this._viewMode = "text";
    this._tableData = [];
    
    // Entity creation defaults (NEW)
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
    return this._viewMode === "table" ? 15 : 10;
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
        if (!this._selectedEntity || !this._allEntities.includes(this._selectedEntity)) {
          this._selectedEntity = this._allEntities[0];
        }
        return;
      }
    }

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

  _parseTableData(rawValue) {
    // Try to parse SNMP walk output format
    const walkPattern = /\[?\('([^']+)',\s*'([^']+)'\),?\]?/g;
    const matches = [...rawValue.matchAll(walkPattern)];
    
    if (matches.length > 0) {
      return matches.map(m => ({ oid: m[1], value: m[2] }));
    }

    // Try to parse line-by-line format: "OID = value"
    const lines = rawValue.split('\n').filter(l => l.trim());
    if (lines.some(l => l.includes('='))) {
      return lines.map(line => {
        const [oid, ...valueParts] = line.split('=');
        return {
          oid: oid.trim(),
          value: valueParts.join('=').trim()
        };
      });
    }

    return [];
  }

  async _copyToClipboard() {
    try {
      // Try modern clipboard API first
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(this._writeValue);
        this._status = "Copied to clipboard";
      } else {
        // Fallback for older browsers or security restrictions
        const textArea = document.createElement('textarea');
        textArea.value = this._writeValue;
        textArea.style.position = 'fixed';
        textArea.style.left = '-999999px';
        textArea.style.top = '-999999px';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        
        const successful = document.execCommand('copy');
        document.body.removeChild(textArea);
        
        if (successful) {
          this._status = "Copied to clipboard";
        } else {
          throw new Error("Copy command failed");
        }
      }
      
      setTimeout(() => {
        if (this._status === "Copied to clipboard") {
          this._status = "";
        }
        this.requestUpdate();
      }, 2000);
      this.requestUpdate();
    } catch (err) {
      console.error("Copy failed:", err);
      // Last resort: show a prompt to manually copy
      this._status = "Copy failed - select text manually";
      
      // Try to select the textarea so user can manually copy
      const textarea = this.shadowRoot.querySelector('textarea');
      if (textarea) {
        textarea.select();
      }
      
      this.requestUpdate();
    }
  }

  _toggleViewMode() {
    if (this._viewMode === "text") {
      const tableData = this._parseTableData(this._writeValue);
      if (tableData.length > 0) {
        this._tableData = tableData;
        this._viewMode = "table";
      } else {
        this._status = "No table data detected";
      }
    } else {
      this._viewMode = "text";
    }
    this.requestUpdate();
  }

  async _sendRead() {
    const targetEntity = this._getTargetEntity();
    if (!targetEntity) {
      this._status = "No hub available";
      this.requestUpdate();
      return;
    }

    this._status = "Reading...";
    this._viewMode = "text"; // Reset to text view
    this._lastReadSuccess = false; // Reset
    this.requestUpdate();

    try {
      if (this._protocol === "modbus") {
        await this._sendModbusRead(targetEntity);
      } else if (this._protocol === "snmp") {
        await this._sendSnmpRead(targetEntity);
      }
      this._lastReadSuccess = true; // Mark success
    } catch (err) {
      console.error("Read error:", err);
      this._status = `Read failed: ${err.message || err}`;
      this._lastReadSuccess = false;
      this.requestUpdate();
    }
  }

  async _sendModbusRead(targetEntity) {
    if (this._modbusAddress === undefined) {
      this._status = "Missing address";
      this.requestUpdate();
      return;
    }

    const result = await this.hass.callWS({
      type: "call_service",
      domain: "protocol_wizard",
      service: "read_register",
      service_data: {
        entity_id: targetEntity,
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

    // Store read data for entity creation (NEW)
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
    } else {
      const value = result?.value ?? result?.response?.value ?? null;
      displayValue = value !== null ? String(value) : "No value";
    }

    this._writeValue = displayValue;
    this._status = "Read OK";
    this.requestUpdate();
  }

  async _sendSnmpRead(targetEntity) {
    if (!this._snmpOid) {
      this._status = "Missing OID";
      this.requestUpdate();
      return;
    }

    const result = await this.hass.callWS({
      type: "call_service",
      domain: "protocol_wizard",
      service: "read_snmp",
      service_data: {
        entity_id: targetEntity,
        oid: this._snmpOid,
        data_type: this._snmpDataType,
      },
      return_response: true,
    });

    const value = result?.value ?? result?.response?.value ?? null;
    
    // Store read data for entity creation (NEW)
    this._lastReadData = {
      address: this._snmpOid,
      data_type: this._snmpDataType,
      value: value,
    };
    
    this._writeValue = value !== null ? String(value) : "No value";
    this._status = "Read OK";
    this.requestUpdate();
  }

  async _sendWrite() {
    const targetEntity = this._getTargetEntity();
    if (!targetEntity) {
      this._status = "No hub available";
      this.requestUpdate();
      return;
    }

    if (this._protocol === "modbus" && this._modbusRegisterType === "auto") {
      this._status = "Can't write with Auto - select Holding or Coil";
      this.requestUpdate();
      return;
    }

    if (!this._writeValue) {
      this._status = "Missing value";
      this.requestUpdate();
      return;
    }

    this._status = "Writing...";
    this.requestUpdate();

    try {
      if (this._protocol === "modbus") {
        await this._sendModbusWrite(targetEntity);
      } else if (this._protocol === "snmp") {
        await this._sendSnmpWrite(targetEntity);
      }
    } catch (err) {
      console.error("Write error:", err);
      this._status = `Write failed: ${err.message || err}`;
      this.requestUpdate();
    }
  }

  async _sendModbusWrite(targetEntity) {
    if (this._modbusAddress === undefined) {
      this._status = "Missing address";
      this.requestUpdate();
      return;
    }

    await this.hass.callWS({
      type: "call_service",
      domain: "protocol_wizard",
      service: "write_register",
      service_data: {
        entity_id: targetEntity,
        address: Number(this._modbusAddress),
        register_type: this._modbusRegisterType || "holding",
        data_type: this._modbusDataType || "uint16",
        byte_order: this._modbusByteOrder || "big",
        word_order: this._modbusWordOrder || "big",
        value: this._parseWriteValue(),
      },
    });

    this._status = "Write OK";
    this.requestUpdate();
  }

  async _sendSnmpWrite(targetEntity) {
    if (!this._snmpOid) {
      this._status = "Missing OID";
      this.requestUpdate();
      return;
    }

    await this.hass.callWS({
      type: "call_service",
      domain: "protocol_wizard",
      service: "write_snmp",
      service_data: {
        entity_id: targetEntity,
        oid: this._snmpOid,
        value: this._parseWriteValue(),
        data_type: this._snmpDataType,
      },
    });

    this._status = "Write OK";
    this.requestUpdate();
  }

  // NEW: Entity creation methods
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
        entity_id: targetEntity,
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
      await this.hass.callService(
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
        <span class="label">Register Type:</span>
        <select .value=${this._modbusRegisterType} @change=${e => this._modbusRegisterType = e.target.value}>
          <option value="auto">Auto-detect</option>
          <option value="holding">Holding (R/W)</option>
          <option value="input">Input (Read Only)</option>
          <option value="coil">Coil (Digital)</option>
          <option value="discrete">Discrete (Digital Read)</option>
        </select>
      </div>

      <div class="field-row">
        <span class="label">Data Type:</span>
        <select .value=${this._modbusDataType} @change=${this._handleModbusDataTypeChange}>
          <option value="uint16">UInt16</option>
          <option value="int16">Int16</option>
          <option value="uint32">UInt32</option>
          <option value="int32">Int32</option>
          <option value="float32">Float32</option>
          <option value="uint64">UInt64</option>
          <option value="int64">Int64</option>
          <option value="string">String</option>
        </select>
      </div>

      <div class="field-row">
        <span class="label">Size:</span>
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
        <span class="label">Byte Order:</span>
        <select .value=${this._modbusByteOrder} @change=${e => this._modbusByteOrder = e.target.value}>
          <option value="big">Big Endian</option>
          <option value="little">Little Endian</option>
        </select>
      </div>

      <div class="field-row">
        <span class="label">Word Order:</span>
        <select .value=${this._modbusWordOrder} @change=${e => this._modbusWordOrder = e.target.value}>
          <option value="big">Big</option>
          <option value="little">Little</option>
        </select>
      </div>

      <div class="field-row checkbox-row">
        <span class="label">Raw Mode:</span>
        <label>
          <input type="checkbox" @change=${e => this._modbusRawMode = e.target.checked} ?checked=${this._modbusRawMode} />
          Enable
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
          <option value="integer">Integer32</option>
          <option value="counter32">Counter32</option>
          <option value="counter64">Counter64</option>
          <option value="gauge32">Gauge32</option>
          <option value="timeticks">TimeTicks</option>
          <option value="ipaddress">IP Address</option>
          <option value="objectid">ObjectID</option>
        </select>
      </div>
    `;
  }

  _renderTableView() {
    if (!this._tableData || this._tableData.length === 0) {
      return html`<div class="no-data">No table data available</div>`;
    }

    return html`
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>OID</th>
              <th>Value</th>
            </tr>
          </thead>
          <tbody>
            ${this._tableData.map((row, idx) => html`
              <tr>
                <td>${idx + 1}</td>
                <td class="oid-cell">${row.oid}</td>
                <td>${row.value}</td>
              </tr>
            `)}
          </tbody>
        </table>
        <div class="table-footer">
          Total: ${this._tableData.length} rows
        </div>
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
            <!-- Device Info -->
            <div class="info">
              Device: ${this.hass.devices?.[this.config.device_id]?.name || "Unknown"}
              &nbsp;|&nbsp;Protocol: ${protocol.toUpperCase()}
              <br>
              Hub: ${this._getTargetEntity() || "Not found"}
            </div>

            <!-- Protocol-specific fields -->
            ${protocol === "modbus" ? this._renderModbusFields() : this._renderSnmpFields()}

            <!-- Value field with view mode toggle -->
            ${this._viewMode === "text" ? html`
              <textarea
                placeholder="Value will appear here"
                .value=${this._writeValue || ""}
                @input=${e => this._writeValue = e.target.value}
                rows="4"
              ></textarea>
            ` : this._renderTableView()}

            <!-- Action buttons -->
            <div class="button-row">
              <button @click=${this._sendRead} class="primary">
                Read
              </button>
              <button @click=${this._sendWrite} class="primary">
                Write
              </button>
            </div>

            <!-- Utility buttons -->
            <div class="button-row secondary-buttons">
              <button @click=${this._copyToClipboard} class="secondary" title="Copy to clipboard">
                Copy
              </button>
              <button @click=${this._toggleViewMode} class="secondary" title="Toggle table view">
                ${this._viewMode === "text" ? "Table View" : "Text View"}
              </button>
            </div>

            <!-- Status message -->
            ${this._status ? html`
              <div class="status ${this._status.includes('OK') || this._status.includes('Copied') ? 'success' : this._status.includes('failed') || this._status.includes('Missing') || this._status.includes("Can't") ? 'error' : 'info'}">
                ${this._status}
              </div>
            ` : ""}

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
        gap: 8px;
      }
      select, input, textarea {
        padding: 8px;
        border-radius: 4px;
        border: 1px solid var(--divider-color);
        background: var(--card-background-color);
        color: var(--primary-text-color);
        font-family: inherit;
      }
      textarea {
        resize: vertical;
        min-height: 80px;
        font-family: 'Courier New', monospace;
      }
      label {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .button-row {
        display: flex;
        gap: 8px;
      }
      .secondary-buttons {
        margin-top: 0px;
      }
      .info {
        padding: 8px;
        background: var(--secondary-background-color);
        border-radius: 4px;
        font-size: 0.9em;
        color: var(--secondary-text-color);
      }
      button {
        flex: 1;
        border: none;
        padding: 10px 20px;
        border-radius: 4px;
        cursor: pointer;
        font-weight: bold;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
      }
      button.primary {
        background: var(--primary-color);
        color: var(--text-primary-color);
      }
      button.secondary {
        background: var(--secondary-background-color);
        color: var(--primary-text-color);
        border: 1px solid var(--divider-color);
      }
      button.cancel-btn {
        background: var(--secondary-text-color);
      }
      button:hover {
        opacity: 0.9;
      }
      .status {
        text-align: center;
        font-weight: bold;
        padding: 8px;
        border-radius: 4px;
      }
      .status.success {
        background: rgba(76, 175, 80, 0.1);
        color: #4caf50;
        border: 1px solid rgba(76, 175, 80, 0.3);
      }
      .status.error {
        background: rgba(244, 67, 54, 0.1);
        color: #f44336;
        border: 1px solid rgba(244, 67, 54, 0.3);
      }
      .status.info {
        background: var(--secondary-background-color);
        color: var(--primary-color);
        border: 1px solid var(--divider-color);
      }
      .field-row {
        display: flex;
        align-items: center;
        margin-bottom: 4px;
      }
      .label {
        width: 120px;
        font-weight: bold;
        font-size: 0.9em;
        color: var(--primary-text-color);
      }
      input, select {
        flex: 1;
        padding: 6px;
      }
      .checkbox-row label {
        display: flex;
        align-items: center;
        cursor: pointer;
      }
      
      /* Table styles */
      .table-container {
        background: var(--card-background-color);
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        overflow: hidden;
      }
      table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.9em;
      }
      thead {
        background: var(--secondary-background-color);
      }
      th {
        padding: 8px;
        text-align: left;
        font-weight: bold;
        border-bottom: 2px solid var(--divider-color);
      }
      td {
        padding: 6px 8px;
        border-bottom: 1px solid var(--divider-color);
      }
      tr:last-child td {
        border-bottom: none;
      }
      tbody tr:hover {
        background: var(--secondary-background-color);
      }
      .oid-cell {
        font-family: 'Courier New', monospace;
        font-size: 0.85em;
      }
      .table-footer {
        padding: 8px;
        background: var(--secondary-background-color);
        font-size: 0.85em;
        color: var(--secondary-text-color);
        text-align: right;
      }
      .no-data {
        padding: 20px;
        text-align: center;
        color: var(--secondary-text-color);
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
        margin-left: 120px;
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
