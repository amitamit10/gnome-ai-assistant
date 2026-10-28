export const calls = {keybindings: {}, removed: [], activated: [], status: [], notifies: []};
export const wm = {
  addKeybinding: (name, settings, flags, modes, handler) => { calls.keybindings[name] = {settings, flags, modes, handler}; },
  removeKeybinding: name => { calls.removed.push(name); },
};
export const panel = {height: 32, addToStatusArea: (id, btn, pos, box) => { calls.status.push({id, pos, box}); }};
export const layoutManager = {primaryMonitor: {x: 0, y: 0, width: 1920, height: 1080}};
export const activateWindow = w => { calls.activated.push(w.title); globalThis.global.display.focus_window = w; };
export const notify = (...a) => calls.notifies.push(a);
