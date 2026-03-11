## Changelog

### [0.7.4] - Ehanced Template Handling
- if you come from 0.7.0 or before: Needs re-install of your devices (should be less painfull then it sounds)
- fixes for drop down / options
- Bacnet working
  
### [0.7.3] - Ehanced Template Handling
- Needs re-install of your devices (should be less painfull then it sounds)
     - Make sure you export your exotic device to a template if you have not done so first!
- Multimaster for modbus serial should now be functional.
- Better hub and multi-device setup for Modbus
- Ground work for adding BACNET. Partly functional atm.

### [0.7.0] - Ehanced Template Handling
- User specific template can be chosen and store separately
- User templates will not be deleted at update (are stored elsewhere)
- Ability to delete User Template
- Poplular language files added
 
### [0.6.0] - MQTT added
- Adding MQTT protocol support
- Includes full read / write with card
  
### [0.5.0] - Entity creation from card
- Adds ability to create entity right from the card after successfull read
- Adds protocol settings attribute to sensors (great for debugging)
- browser cache needs to be emptied for card updates (CTRL-SHIFT-R in browser window)

### [0.4.8] - Nr entity error message fix

### [0.4.7] - Bug in selecting Device_class, state_class, entity_class
- Also bug in translation file (json doet allow braces character)
  
### [0.4.6] - Device_class, state_class and icon
- Added support in integration and template for device_class, state_class and icon
- Update some templates with device_class, state_class and icons
- Added 'detele all' option to delete all entities

### [0.4.5] - Template export added
- Template export function

### [0.4.4] - Small fix
- Fix for first issue for new installs
  
### [0.4.3] - About templates...
- Installation via template possible
- Added several base templates

### [0.4.1] - Update
- Error in en.json
- wrong card version
  
### [0.4.0] - Stable release
- SNMP and Modbus now fully support also in card and templates
- several bugs fixed
- More hardening of non happy flows.

### [0.3.0] - Public Release
- Tried and tested

### [0.2.1] - Device tamplates and other Major additions
- Added format strings
  
### [0.2.0] - Device tamplates and other Major additions
- Fully tested and working Modbus and SNMP support
- Many improvements
- Ready for addtional protocols
  
### [0.1.1] - Device tamplates and other Major additions
- Add SNMP in framework
- rework Modbus
  
### [0.1.0] - Early release
- Architecture setup
