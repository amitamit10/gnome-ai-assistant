// AI Assistant: top-bar button + keyboard shortcut for the chat window.
//
// This extension is deliberately thin. It never spawns processes: it asks the backend service to open the chat
// over D-Bus (io.github.aiassistant.Control.Open, which D-Bus-activates the service if needed), then positions and
// dismisses the window the service opens. Everything else (chat, search, voice) lives in the service.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const BUS_NAME = 'io.github.aiassistant.Service';
const CONTROL_PATH = '/io/github/aiassistant/Control';
const CONTROL_IFACE = 'io.github.aiassistant.Control';
const TITLE = 'AI Assistant';   // the chat page's <title>; a browser app window is titled exactly like its page
const WIDTH = 720;
const HEIGHT = 680;
const DEBOUNCE_MS = 4000;

export default class AIAssistant extends Extension {
    enable() {
        this._settings = this.getSettings();
        this._armed = false;       // true once the chat window has had focus (so opening it does not close it)
        this._closeId = 0;
        this._pollId = 0;
        this._lastLaunch = 0;
        this._cancellable = new Gio.Cancellable();

        this._button = null;
        this._syncButton();
        this._settingsId = this._settings.connect('changed::show-panel-button', () => this._syncButton());

        Main.wm.addKeybinding('toggle-chat', this._settings, Meta.KeyBindingFlags.NONE,
            Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW, () => this._safe(() => this._toggle()));

        this._focusId = global.display.connect('notify::focus-window', () => this._safe(() => this._onFocusChanged()));
    }

    disable() {
        Main.wm.removeKeybinding('toggle-chat');
        if (this._focusId) {
            global.display.disconnect(this._focusId);
            this._focusId = 0;
        }
        if (this._settingsId) {
            this._settings.disconnect(this._settingsId);
            this._settingsId = 0;
        }
        for (const id of [this._closeId, this._pollId]) {
            if (id)
                GLib.source_remove(id);
        }
        this._closeId = this._pollId = 0;
        this._cancellable?.cancel();
        this._cancellable = null;
        this._button?.destroy();
        this._button = null;
        this._settings = null;
    }

    _safe(fn) {
        try {
            fn();
        } catch (e) {
            logError(e, 'AI Assistant extension');
        }
    }

    _syncButton() {
        const want = this._settings.get_boolean('show-panel-button');
        if (want && !this._button) {
            this._button = new PanelMenu.Button(0.0, 'AI Assistant', true);
            this._button.add_child(new St.Icon({
                icon_name: 'chat-message-new-symbolic',
                style_class: 'system-status-icon',
            }));
            this._button.connect('button-press-event', () => {
                this._safe(() => this._toggle());
                return Clutter.EVENT_STOP;
            });
            Main.panel.addToStatusArea(this.uuid, this._button, 0, 'right');
        } else if (!want && this._button) {
            this._button.destroy();
            this._button = null;
        }
    }

    _findWindow() {
        // exact title: a normal browser tab would be "AI Assistant - <browser name>"
        return global.get_window_actors()
            .map(a => a.meta_window)
            .find(w => w.get_title() === TITLE && w.get_window_type() === Meta.WindowType.NORMAL) ?? null;
    }

    _toggle() {
        const w = this._findWindow();
        if (w && w === global.display.focus_window) {
            w.delete(global.get_current_time());       // toggle off; the service keeps the conversation
        } else if (w) {
            Main.activateWindow(w);
        } else {
            this._launch();
        }
    }

    _launch() {
        const now = GLib.get_monotonic_time() / 1000;
        if (this._lastLaunch && now - this._lastLaunch < DEBOUNCE_MS)
            return;
        this._lastLaunch = now;

        // Open() D-Bus-activates the service when it is not running yet.
        Gio.DBus.session.call(BUS_NAME, CONTROL_PATH, CONTROL_IFACE, 'Open', null, null,
            Gio.DBusCallFlags.NONE, 30000, this._cancellable, (conn, res) => {
                try {
                    conn.call_finish(res);
                } catch (e) {
                    if (!e.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED)) {
                        Main.notify('AI Assistant',
                            'The assistant service is not available. Is gnome-ai-assistant installed? (' + e.message + ')');
                    }
                }
            });

        let tries = 0;
        this._armed = false;
        if (this._pollId)
            GLib.source_remove(this._pollId);
        this._pollId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 150, () => {
            const w = this._findWindow();
            if (w) {
                this._place(w);
                this._pollId = 0;
                return GLib.SOURCE_REMOVE;
            }
            if (++tries > 120) {   // ~18 s
                this._pollId = 0;
                return GLib.SOURCE_REMOVE;
            }
            return GLib.SOURCE_CONTINUE;
        });
    }

    _place(w) {
        const mon = Main.layoutManager.primaryMonitor;
        const x = mon.x + Math.round((mon.width - WIDTH) / 2);
        const y = mon.y + Main.panel.height + 24;
        w.unmaximize(Meta.MaximizeFlags.BOTH);
        w.move_resize_frame(false, x, y, WIDTH, Math.min(HEIGHT, mon.height - Main.panel.height - 48));
        w.make_above();
        Main.activateWindow(w);
    }

    _onFocusChanged() {
        const f = global.display.focus_window;
        const chat = this._findWindow();
        if (chat && f === chat) {
            this._armed = true;
            if (this._closeId) {
                GLib.source_remove(this._closeId);
                this._closeId = 0;
            }
            return;
        }
        // chat lost focus: close it shortly (click-away dismiss), unless focus comes back
        if (chat && this._armed && !this._closeId && this._settings.get_boolean('close-on-focus-out')) {
            this._closeId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 350, () => {
                this._closeId = 0;
                const c = this._findWindow();
                if (c && global.display.focus_window !== c)
                    c.delete(global.get_current_time());
                this._armed = false;
                return GLib.SOURCE_REMOVE;
            });
        }
    }
}
