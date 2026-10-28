// Preferences: the shortcut, close-on-click-away, and the top-bar button.
import Adw from 'gi://Adw';
import Gtk from 'gi://Gtk';

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

export default class AIAssistantPrefs extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        const page = new Adw.PreferencesPage({title: 'AI Assistant', icon_name: 'chat-message-new-symbolic'});
        const group = new Adw.PreferencesGroup({title: 'Chat window'});
        page.add(group);

        const shortcut = new Adw.EntryRow({
            title: 'Shortcut (comma separated, e.g. <Super>slash, <Super>backslash)',
            text: settings.get_strv('toggle-chat').join(', '),
            show_apply_button: true,
        });
        shortcut.connect('apply', () => {
            const keys = shortcut.text.split(',').map(s => s.trim()).filter(Boolean);
            settings.set_strv('toggle-chat', keys);
        });
        group.add(shortcut);

        const addSwitch = (key, title, subtitle) => {
            const row = new Adw.SwitchRow({title, subtitle});
            settings.bind(key, row, 'active', 0 /* Gio.SettingsBindFlags.DEFAULT */);
            group.add(row);
        };
        addSwitch('close-on-focus-out', 'Close when clicking elsewhere', 'The conversation is kept by the background service.');
        addSwitch('show-panel-button', 'Show the top-bar button', 'You can always use the keyboard shortcut.');

        window.add(page);
    }
}
