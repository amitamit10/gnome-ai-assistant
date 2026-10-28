// Runs the real extension.js against stub GNOME Shell APIs. Usage: gjs -m test.js <path/to/extension.js>
import GLib from 'gi://GLib';
import {state} from './stubs/extension.js';
import * as Main from './stubs/main.js';
import {calls as gio} from './stubs/gio.js';
import {log} from './stubs/glib.js';

const extPath = ARGV[0];
const {default: AIAssistant} = await import(`file://${extPath}`);

let fails = 0;
const ok = (cond, msg) => { print((cond ? 'PASS ' : 'FAIL ') + msg); if (!cond) fails++; };

class FakeWindow {
  constructor(title, type = 0) { this.title = title; this.type = type; this.calls = []; }
  get_title() { return this.title; }
  get_window_type() { return this.type; }
  unmaximize() { this.calls.push('unmaximize'); }
  move_resize_frame(user, x, y, w, h) { this.calls.push(['move', x, y, w, h]); this.geom = {x, y, w, h}; }
  make_above() { this.calls.push('above'); }
  delete() { this.calls.push('delete'); this.deleted = true; }
}
const windows = [], focusHandlers = [];
globalThis.logError = (e, m) => print('logError: ' + m + ': ' + e);
globalThis.global = {
  display: {focus_window: null, connect: (s, cb) => { focusHandlers.push(cb); return focusHandlers.length; }, disconnect: id => { focusHandlers[id - 1] = null; }},
  get_window_actors: () => windows.map(w => ({meta_window: w})),
  get_current_time: () => 1234,
};
const fire = () => { for (const [id, t] of [...log.timers]) { if (t.cb() === false) log.timers.delete(id); } };
const setFocus = w => { globalThis.global.display.focus_window = w; focusHandlers.forEach(h => h && h()); };
const hotkey = () => Main.calls.keybindings['toggle-chat'].handler();

const ext = new AIAssistant();
ext.enable();
ok(Main.calls.keybindings['toggle-chat'] !== undefined && Main.calls.keybindings['toggle-chat'].modes === 3, 'keybinding registered for NORMAL|OVERVIEW');
ok(Main.calls.status.length === 1 && Main.calls.status[0].box === 'right', 'top-bar button added');

// 1) no window yet -> asks the service to open it over D-Bus (never spawns a process)
hotkey();
ok(gio.dbus.length === 1 && gio.dbus[0].method === 'Open' && gio.dbus[0].name === 'io.github.aiassistant.Service' && gio.dbus[0].path === '/io/github/aiassistant/Control', 'hotkey calls Control.Open on the service');
hotkey();
ok(gio.dbus.length === 1, 'rapid second press is debounced');

// 2) window appears -> placed; a normal browser tab is ignored
const decoy = new FakeWindow('AI Assistant - Google Chrome'); windows.push(decoy); fire();
ok(!decoy.calls.length, 'a normal browser tab titled "AI Assistant - ..." is ignored');
const chat = new FakeWindow('AI Assistant'); windows.push(chat); fire();
ok(chat.geom && chat.geom.w === 720 && chat.geom.x === 600 && chat.geom.y === 56, 'window centred at the top: ' + JSON.stringify(chat.geom));
ok(chat.calls.includes('above') && Main.calls.activated.includes('AI Assistant'), 'window raised and activated');
ok(log.timers.size === 0, 'poll timer cleaned up');

// 3) click-away closes after it had focus; refocus cancels
setFocus(chat); const other = new FakeWindow('Terminal'); windows.push(other); setFocus(other);
ok(log.timers.size === 1, 'losing focus schedules a close'); fire();
ok(chat.deleted === true, 'chat closed after click-away');
chat.deleted = false; setFocus(chat); setFocus(other); setFocus(chat); fire();
ok(chat.deleted !== true, 'regaining focus cancels the close');

// 4) the close-on-focus-out setting is honoured
state.settings['close-on-focus-out'] = false; chat.deleted = false;
setFocus(chat); setFocus(other);
ok(log.timers.size === 0, 'no close is scheduled when the setting is off');
state.settings['close-on-focus-out'] = true;

// 5) toggling
setFocus(chat); hotkey();
ok(chat.deleted === true, 'hotkey while focused closes the window');
chat.deleted = false; Main.calls.activated.length = 0; setFocus(other); hotkey();
ok(Main.calls.activated.includes('AI Assistant') && !chat.deleted, 'hotkey while open but unfocused raises it');

// 6) service missing -> a helpful notification, no crash
windows.length = 0; log.clock = GLib.get_monotonic_time() + 10_000_000;   // jump past the debounce
gio.failNext = new Error('ServiceUnknown'); hotkey();
ok(Main.calls.notifies.length === 1 && /not available/.test(Main.calls.notifies[0][1]), 'unreachable service shows a notification');

// 7) errors never escape; the panel button can be toggled live
const bad = new AIAssistant(); bad.enable();
globalThis.global.get_window_actors = () => { throw new Error('boom'); };
let threw = false; try { hotkey(); } catch (e) { threw = true; }
ok(!threw, 'an exception in a handler is caught, not thrown into the Shell');
globalThis.global.get_window_actors = () => windows.map(w => ({meta_window: w}));
state.settings['show-panel-button'] = false; state.handlers['changed::show-panel-button']();   // handler belongs to `bad` (last enabled)
ok(bad._button === null, 'turning the button off in settings removes it live');

// 8) disable cleans up and cancels the pending D-Bus call
ext.disable();
ok(Main.calls.removed.includes('toggle-chat') && gio.cancelled >= 1, 'disable removes the keybinding and cancels D-Bus calls');
print(fails ? `\n${fails} FAILED` : '\nALL PASSED');
imports.system.exit(fails ? 1 : 0);
