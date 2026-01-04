import { LitElement, html, css } from "https://unpkg.com/lit?module";

class ProtocolWizardCard extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      config: { type: Object },
      _selectedEntity: { type: String },
      _selectedAddress: { type: Number },
      _selectedSize: { type: Number },
      _writeValue: { type: String },
      _writeAddress: { type: Number },
      _allEntities: { type: Array },
      _selectedStatus: { type: String },
      _writeStatus: { type: String },
      _dataType: { type: String },
      _writeDataType: { type: String },
      _registerType: { type: String },
      _byteOrder: { type: String },
      _wordOrder: { type: String },
      _writeByteOrder: { type: String },
      _writeWordOrder: { type: String },
      _rawMode: { type: Boolean },
    };
  }

  constructor() {
    super();
    this._selectedEntity = "";
    this._selectedAddress = 0;
    this._selectedSize = 1;
    this._writeValue = "";
    this._writeAddress = 0;
    this._allEntities = [];
    this._selectedStatus = "";
    this._writeStatus = "";
    this._dataType = "uint16";
    this._writeDataType = "uint16";
    this._registerType = "auto";
    this._byteOrder = "big";
    this._wordOrder = "big";
    this._writeByteOrder = "big";
    this._writeWordOrder = "big";
    this._rawMode = false;
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

    if (changedProps.has("hass")) {
      this._resolveDeviceEntities();
    }
  }

  _resolveDeviceEntities() {
    if (!this.hass) return;

    this._allEntities = [];
    const deviceId = this.config.device_id;

    const entityRegistry = this.hass.entities;

    // Preferred: entities belonging to selected device
    if (deviceId && entityRegistry) {
      const deviceEntities = Object.values(entityRegistry)
        .filter(e => e.device_id === deviceId)
        .map(e => e.entity_id)
        .sort();

      if (deviceEntities.length > 0) {
        this._allEntities = deviceEntities;

        if (
          !this._selectedEntity ||
          !this._allEntities.includes(this._selectedEntity)
        ) {
          this._selectedEntity = this._allEntities[0];
        }
        return;
      }
    }

    // Fallback: all Modbus Wizard entities (registry-based)
    if (entityRegistry) {
      this._allEntities = Object.values(entityRegistry)
        .filter(e => e.platform === "protocol_wizard")
        .map(e => e.entity_id)
        .sort();
    }

    // Final fallback: states (legacy / early-load safety)
    if (this._allEntities.length === 0) {
      this._allEntities = Object.keys(this.hass.states)
        .filter(eid => {
          const state = this.hass.states[eid];
          return state?.attributes?.integration === "protocol_wizard";
        })
        .sort();
    }
  }

  _getTargetEntity() {
    // If a specific entity was selected, use it
    if (this._selectedEntity) {
      return this._selectedEntity;
    }

    // Priority 1: Find the hub entity (ends with _hub)
    if (this._allEntities.length > 0) {
      const hubEntity = this._allEntities.find(eid => eid.includes("_hub"));
      if (hubEntity) {
        return hubEntity;
      }
    }

    // Priority 2: Use first entity from device
    if (this._allEntities.length > 0) {
      return this._allEntities[0];
    }

    // Priority 3: Search by device_id
    if (this.config.device_id) {
      const eid = Object.keys(this.hass.states).find(
        eid => this.hass.states[eid]?.attributes?.device_id === this.config.device_id
      );
      return eid || null;
    }

    return null;
  }

  _handleDataTypeChange(e) {
    this._dataType = e.target.value;
    const sizes = {
      "uint16": 1,
      "int16": 1,
      "uint32": 2,
      "int32": 2,
      "float32": 2,
      "uint64": 4,
      "int64": 4,
      "string": 1,
    };
    this._selectedSize = sizes[this._dataType] || 1;
    this.requestUpdate();
  }

  _parseWriteValue() {
    if (!this._writeValue) return 0;
    
    // Try to parse as number
    const num = Number(this._writeValue);
    if (!isNaN(num)) return num;
    
    // Return as string for string types
    return this._writeValue;
  }

  async _sendRead() {
    const targetEntity = this._getTargetEntity();
    if (!targetEntity) {
      this._selectedStatus = "No Modbus hub available";
      this.requestUpdate();
      return;
    }

    if (this._selectedAddress === undefined) {
      this._selectedStatus = "Missing address";
      this.requestUpdate();
      return;
    }

    this._selectedStatus = "Reading...";
    this.requestUpdate();

    try {
      const result = await this.hass.callWS({
        type: "call_service",
        domain: "protocol_wizard",
        service: "read_register",
        service_data: {
          entity_id: targetEntity,
          address: Number(this._selectedAddress),
          register_type: this._registerType || "auto",
          data_type: this._dataType || "uint16",
          ...(this._selectedSize ? { size: Number(this._selectedSize) } : {}),
          byte_order: this._byteOrder || "big",
          word_order: this._wordOrder || "big",
          raw: this._rawMode,
        },
        return_response: true,
      });

      // Check different possible response structures
      let displayValue = "";

      // Extract the raw value (registers array or bits)
      let rawData = null;
      if (result?.value !== undefined && typeof result.value === "object") {
        rawData = result.value;
      } else if (result?.response?.value !== undefined && typeof result.response.value === "object") {
        rawData = result.response.value;
      }

      if (this._rawMode && rawData) {
        // Assume rawData has .registers (array of numbers) and optionally .bits
        const registers = rawData.registers || [];
        const bits = rawData.bits || [];

        // HEX view
        const hex = registers.map(r => `0x${r.toString(16).toUpperCase().padStart(4, '0')}`).join(' ');
        
        // ASCII view (best effort)
        let ascii = '';
        try {
          const bytes = new Uint8Array(registers.flatMap(r => [r >> 8, r & 0xFF]));
          ascii = new TextDecoder('ascii', { fatal: false }).decode(bytes).replace(/\0/g, '').trim();
          if (ascii === '') ascii = '(no printable ASCII)';
        } catch {
          ascii = '(invalid ASCII)';
        }

        // Binary/bitwise view
        const binary = registers.map(r => r.toString(2).padStart(16, '0')).join(' ');

        // Bits view if available
        const bitsView = bits.length > 0 ? `Bits: [${bits.map(b => b ? 1 : 0).join(', ')}]` : '';

        // Combine all
        displayValue = `HEX: ${hex}\n ASCII: ${ascii}\n Binary: ${binary}`;
        if (bitsView) displayValue += `\n${bitsView}`;
        if (rawData.detected_type) displayValue += `\n Type: ${rawData.detected_type}`;
      } else {
        // Normal decoded value
        const value = result?.value ?? result?.response?.value ?? null;
        displayValue = value !== null ? String(value) : "No value";
      }

      this._writeValue = displayValue;
      this._selectedStatus = "Read OK";
    } catch (err) {
      console.error("Read error:", err);
      this._selectedStatus = `Read failed: ${err.message || err}`;
    }

    this.requestUpdate();
  }

  async _sendWrite() {
    const targetEntity = this._getTargetEntity();
    if (!targetEntity) {
      this._writeStatus = "No Modbus hub available";
      this.requestUpdate();
      return;
    }

    if (this._writeAddress === undefined || this._writeValue === undefined) {
      this._writeStatus = "Missing address or value";
      this.requestUpdate();
      return;
    }

    this._writeStatus = "Writing...";
    this.requestUpdate();

    try {
      await this.hass.callWS({
        type: "call_service",
        domain: "protocol_wizard",
        service: "write_register",
        service_data: {
          entity_id: targetEntity,
          address: Number(this._writeAddress),
          value: this._parseWriteValue(),
          data_type: this._writeDataType || "uint16",
          byte_order: this._writeByteOrder || "big",
          word_order: this._writeWordOrder || "big",
        },
      });

      this._writeStatus = "Write OK";
    } catch (err) {
      console.error("Write error:", err);
      this._writeStatus = `Write failed: ${err.message || err}`;
    }

    this.requestUpdate();
  }
  
  render() {
    if (!this.hass || !this.config) return html``;

    return html`
      <ha-card>
        ${this.config.name ? html`
          <div class="header">${this.config.name}</div>
        ` : ""}

        <div class="section">
          <div class="section-title">Read / Write Register</div>

          <div class="write-section">
            <!-- Modbus Device -->
            ${this.config.device_id ? html`
              <div class="info">
                Using device: ${this.hass.devices?.[this.config.device_id]?.name || "Modbus Device"}
                <br>
                Hub entity: ${this._getTargetEntity() || "Not found"}
              </div>
            ` : html`
              <select @change=${e => this._selectedEntity = e.target.value}>
                <option value="">Select Modbus Entity</option>
                ${this._allEntities.map(eid => html`
                  <option value="${eid}" ?selected=${eid === this._selectedEntity}>
                    ${eid}
                  </option>
                `)}
              </select>
            `}
            <div class="field-row">
              <span class="label">Register Address:</span>
              <input
                type="number"
                placeholder="e.g. 100"
                min="0"
                max="65535"
                .value=${this._selectedAddress}
                @input=${e => this._selectedAddress = Number(e.target.value)}
              />
            </div>

            <div class="field-row">
              <span class="label">Register Category:</span>
              <select .value=${this._registerType} @change=${e => this._registerType = e.target.value}>
                <option value="auto">Auto-detect</option>
                <option value="holding">Holding Register (Read/Write)</option>
                <option value="input">Input Register (Read Only)</option>
                <option value="coil">Coil (Digital Out)</option>
                <option value="discrete">Discrete Input (Digital In)</option>
              </select>
            </div>

            <div class="field-row">
              <span class="label">Data Format:</span>
              <select .value=${this._dataType} @change=${this._handleDataTypeChange}>
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
                .value=${this._selectedSize}
                @input=${e => this._selectedSize = Number(e.target.value)}
              />
            </div>


            <div class="field-row">
              <span class="label">Endianness (Byte):</span>
              <select .value=${this._byteOrder} @change=${e => this._byteOrder = e.target.value}>
                <option value="big">Big Endian (ABCD)</option>
                <option value="little">Little Endian (DCBA)</option>
              </select>
            </div>

            <div class="field-row">
              <span class="label">Endianness (Word):</span>
              <select .value=${this._wordOrder} @change=${e => this._wordOrder = e.target.value}>
                <option value="big">Big Word (Most Significant First)</option>
                <option value="little">Little Word (Least Significant First)</option>
              </select>
            </div>

            <div class="field-row checkbox-row">
              <span class="label">Bypass Processing:</span>
              <label>
                <input type="checkbox" @change=${e => this._rawMode = e.target.checked} ?checked=${this._rawMode} />
                Enable Raw Mode
              </label>
            </div>

            <input
              type="text"
              placeholder="Value"
              .value=${this._writeValue || ""}
              @input=${e => this._writeValue = e.target.value}
            />

            <div class="button-row">
              <button @click=${this._sendRead}>Read</button>
              <button @click=${this._sendWrite}>Write</button>
            </div>

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
        width: 160px; /* Fixed width ensures all inputs align vertically */
        font-weight: bold;
        font-size: 0.9em;
        color: var(--primary-text-color);
      }

      input, select {
        flex: 1; /* Makes the input fill the remaining space */
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
  description: "Protocol Wizard Device Manipulation integration",
  preview: true,
});
