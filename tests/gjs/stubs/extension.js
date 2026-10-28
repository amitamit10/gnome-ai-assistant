export const state = {settings: {'show-panel-button': true, 'close-on-focus-out': true}, handlers: {}};
export class Extension {
  constructor() { this.uuid = 'ai-assistant@aiassistant.github.io'; }
  getSettings() {
    return {
      get_boolean: k => state.settings[k],
      connect: (sig, cb) => { state.handlers[sig] = cb; return 7; },
      disconnect: () => {},
    };
  }
}
