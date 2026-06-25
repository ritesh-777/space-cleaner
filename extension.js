/**
 * GNOME Space Cleaner Extension
 * =============================
 * Author: Ritesh (GitHub: ritesh-777)
 * License: GNU GPLv3
 * GNOME Shell Compatibility: GNOME 45, 46, 47, 48, 49, 50, 51+ (ESM modules)
 *
 * This extension adds an interactive space-cleaning utility to the GNOME top panel.
 * It coordinates with a Python backend script (`cleaner-helper.py`) asynchronously 
 * using GJS subprocess bindings to keep the main shell thread silky-smooth and lag-free.
 */

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import Pango from 'gi://Pango';

// GNOME UI components must be imported as ES Modules (ESM) namespaces in GNOME 45+.
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

// The base Extension class must be extended by the default export.
import {Extension, gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

/**
 * Cleanable space categories configuration containing display names and descriptions.
 */
const CATEGORIES = {
    'trash': { 
        label: 'Trash Bin', 
        desc: 'Holds files you have deleted. Emptying this is completely safe and permanently removes them.' 
    },
    'thumbnails': { 
        label: 'Thumbnail Cache', 
        desc: 'Stores cached previews of images and videos. Cleaning is safe; GNOME will regenerate them as needed.' 
    },
    'font_cache': {
        label: 'Font Cache',
        desc: 'Stores generated font lookup caches. Cleaning is safe; fontconfig rebuilds them automatically when applications need fonts.'
    },
    'flatpak': { 
        label: 'Flatpak Cache', 
        desc: 'Stores temporary caches from Flatpak applications. Cleaning is safe and won\'t affect your installed apps.' 
    },
    'snap': { 
        label: 'Snap Cache', 
        desc: 'Stores Snap package download archives and disabled revisions. Cleaning is safe and reclaims a lot of space.' 
    },
    'packages': { 
        label: 'OS Package Cache', 
        desc: 'Cached package archives from updates/installs. Cleaning is safe; package manager will fetch new lists online.' 
    },
    'aur_packages': {
        label: 'AUR Packages',
        desc: 'Built AUR package artifacts and Pamac build files from helpers such as Yay, Paru, Pikaur, Trizen, and Pamac. These can be rebuilt when needed.'
    },
    'journal': { 
        label: 'System Journal', 
        desc: 'Logs recorded by system services. Cleaning vacuums them down to 50MB, preserving recent diagnostics.' 
    },
    'coredumps': {
        label: 'System Coredumps',
        desc: 'Crash dump files saved for debugging past application crashes. Cleaning is safe if you do not need to inspect old crashes.'
    },
    'dev_caches': { 
        label: 'Developer Caches', 
        desc: 'Caches from NPM, Yarn, and Pip. Safe to clean; tools will re-download packages from registries when needed.' 
    },
    'browser_cache': {
        label: 'Browser Cache (Separate)',
        desc: 'Warning: separate from Clean All because pages may load slower after cleaning and offline web caches may be rebuilt. Cookies, history, and saved logins are not cleaned.',
        cleanAll: false
    },
    'shader_cache': {
        label: 'Shader Cache (Separate)',
        desc: 'Warning: separate from Clean All because games and graphics apps may stutter while shaders rebuild after cleaning.',
        cleanAll: false
    }
};

/**
 * Format bytes to human-readable strings (e.g. 1.2 GB, 450.5 MB).
 * 
 * @param {number} bytes - Size in bytes.
 * @returns {string} Human-readable file size string.
 */
function formatBytes(bytes) {
    if (bytes <= 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

/**
 * GNOME Space Cleaner Extension Class
 * Extends the official GNOME Extension base class to hook into lifecycle states.
 */
export default class SpaceCleanerExtension extends Extension {
    /**
     * Extension activation lifecycle hook.
     * Triggered when the extension is toggled "ON" in GNOME. Instantiates widgets.
     */
    enable() {
        // Instantiate the top panel indicator button
        this._indicator = new PanelMenu.Button(0.0, _('Space Cleaner'));
        
        // 1. Setup Status Panel Icon (standard symbolic style)
        let icon = new St.Icon({
            gicon: new Gio.ThemedIcon({name: 'user-trash-symbolic'}),
            style_class: 'system-status-icon',
        });
        this._indicator.add_child(icon);

        // 2. Setup the Dropdown Menu Box Container
        this._menuBox = new St.BoxLayout({
            vertical: true,
            style_class: 'space-cleaner-menu-box'
        });

        // Header Title Label
        let titleLabel = new St.Label({
            text: _('GNOME Space Cleaner'),
            style_class: 'space-cleaner-header'
        });
        this._menuBox.add_child(titleLabel);

        // Summary Text Label (displays total cleanable space)
        this._summaryLabel = new St.Label({
            text: _('Scanning system space...'),
            style_class: 'space-cleaner-summary'
        });
        this._menuBox.add_child(this._summaryLabel);

        // Populate Category Rows as native GNOME Submenus
        this._rows = {};
        for (let key in CATEGORIES) {
            // PopupSubMenuMenuItem provides smooth drop-down collapse/expand behaviors
            let subMenu = new PopupMenu.PopupSubMenuMenuItem(CATEGORIES[key].label);
            if (key === 'aur_packages')
                subMenu.hide();
            
            // Current Size Label inserted before the drop-down expander triangle arrow
            let sizeLabel = new St.Label({
                text: '...',
                style_class: 'space-cleaner-row-size',
                y_align: Clutter.ActorAlign.CENTER
            });
            // Index offset: length - 1 places it directly to the left of the arrow
            subMenu.insert_child_at_index(sizeLabel, subMenu.get_children().length - 1);

            // Container box positioned inside the collapsed dropdown drawer
            let subMenuBox = new St.BoxLayout({
                vertical: true,
                style_class: 'space-cleaner-sub-box'
            });

            // Localized Description Card (word wraps safely using Pango)
            let descLabel = new St.Label({
                text: CATEGORIES[key].desc,
                style_class: 'space-cleaner-desc',
                x_expand: true
            });
            descLabel.clutter_text.line_wrap = true;
            descLabel.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
            subMenuBox.add_child(descLabel);

            // Action Button for cleaning just this specific category
            let btn = new St.Button({
                label: CATEGORIES[key].cleanAll === false ? 'Clean Separately' : 'Clean Category',
                style_class: 'space-cleaner-sub-btn',
                x_expand: true
            });
            btn.connect('clicked', () => this._cleanCategory(key));
            subMenuBox.add_child(btn);

            // Append the submenu box to the collapsible popup box
            subMenu.menu.box.add_child(subMenuBox);

            // Store row reference coordinates for dynamic runtime changes
            this._rows[key] = {
                item: subMenu,
                sizeLabel: sizeLabel,
                btn: btn
            };

            // Register the submenu item in the panel menu list
            this._indicator.menu.addMenuItem(subMenu);
        }

        // Add a standard GNOME Separator
        this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // Footer layout block
        let footer = new St.BoxLayout({
            vertical: false,
            style_class: 'space-cleaner-footer-box'
        });

        // Scan/Refresh Button
        this._refreshBtn = new St.Button({
            label: 'Scan / Refresh',
            style_class: 'space-cleaner-btn-action space-cleaner-btn-refresh',
            x_expand: true
        });
        this._refreshBtn.connect('clicked', () => this._scanSystem());
        footer.add_child(this._refreshBtn);

        // "Clean All" Destructive Action Button
        this._cleanAllBtn = new St.Button({
            label: 'Clean All',
            style_class: 'space-cleaner-btn-action space-cleaner-btn-cleanall',
            x_expand: true
        });
        this._cleanAllBtn.connect('clicked', () => this._cleanAll());
        footer.add_child(this._cleanAllBtn);

        this._menuBox.add_child(footer);

        // Insert the header block container at the very top of the popup box index
        this._indicator.menu.box.insert_child_at_index(this._menuBox, 0);

        // 3. Register the indicator button in the panel status bar area
        Main.panel.addToStatusArea(this.uuid, this._indicator);

        // 4. Fire the initial system storage scan
        this._scanSystem();
    }

    /**
     * Extension deactivation lifecycle hook.
     * Triggered when the extension is toggled "OFF" or uninstalled. Cleanly destroys actors.
     */
    disable() {
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
        this._rows = null;
        this._menuBox = null;
    }

    /**
     * Get the absolute filesystem path of the cleaner-helper.py script inside extension dir.
     * 
     * @returns {string} The path to cleaner-helper.py.
     */
    _getHelperPath() {
        return this.dir.get_path() + '/cleaner-helper.py';
    }

    /**
     * Executes the Python backend helper asynchronously in a separate process pipeline.
     * Uses Gio.Subprocess to prevent blocking the GNOME Shell JavaScript main thread.
     * 
     * @param {string[]} args - Command line arguments passed to the python script.
     * @param {function} callback - Callback function receiving (stdout_string, error_object).
     */
    _runHelperAsync(args, callback) {
        try {
            let helperPath = this._getHelperPath();
            let argv = ['python3', helperPath].concat(args);
            let proc = new Gio.Subprocess({
                argv: argv,
                flags: Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
            });
            proc.init(null);
            proc.communicate_utf8_async(null, null, (obj, res) => {
                try {
                    let [success, stdout, stderr] = obj.communicate_utf8_finish(res);
                    if (success) {
                        callback(stdout, null);
                    } else {
                        callback(null, new Error(stderr || 'Subprocess execution failed.'));
                    }
                } catch (err) {
                    callback(null, err);
                }
            });
        } catch (err) {
            callback(null, err);
        }
    }

    /**
     * Scans the directories asynchronously. Deactivates controls during the process.
     */
    _scanSystem() {
        this._summaryLabel.set_text(_('Scanning system...'));
        for (let key in this._rows) {
            this._rows[key].sizeLabel.set_text('...');
            this._rows[key].btn.sensitive = false; // Disable until size is calculated
        }
        this._refreshBtn.sensitive = false;
        this._cleanAllBtn.sensitive = false;

        this._runHelperAsync(['scan'], (stdout, err) => {
            // Restore controls
            this._refreshBtn.sensitive = true;
            this._cleanAllBtn.sensitive = true;

            if (err) {
                this._summaryLabel.set_text(_('Scan error: ' + err.message));
                return;
            }

            try {
                let data = JSON.parse(stdout.trim());
                let totalCleanable = 0;

                for (let key in this._rows) {
                    if (key === 'aur_packages') {
                        if (data['arch_based'])
                            this._rows[key].item.show();
                        else {
                            this._rows[key].item.hide();
                            continue;
                        }
                    }

                    let bytes = data[key] || 0;
                    if (CATEGORIES[key].cleanAll !== false)
                        totalCleanable += bytes;
                    this._rows[key].sizeLabel.set_text(formatBytes(bytes));
                    // A category is cleanable/sensitive only if its size exceeds 0 bytes
                    this._rows[key].btn.sensitive = bytes > 0;

                    // Dynamic label for system packages (displays detected package manager name)
                    if (key === 'packages' && data['packages_mgr'] && data['packages_mgr'] !== 'None') {
                        this._rows[key].item.label.set_text(`${data['packages_mgr']} Cache`);
                    }
                }

                this._cleanAllBtn.sensitive = totalCleanable > 0;
                this._summaryLabel.set_text(_(`Clean All space: ${formatBytes(totalCleanable)} (separate items excluded)`));
            } catch (jsonErr) {
                this._summaryLabel.set_text(_('Failed to parse scan metrics.'));
            }
        });
    }

    /**
     * Cleans a specific storage category asynchronously.
     * 
     * @param {string} key - The category identifier key (e.g. 'trash', 'packages').
     */
    _cleanCategory(key) {
        let rowObj = this._rows[key];
        rowObj.btn.sensitive = false;
        rowObj.btn.set_label('Cleaning...');

        this._runHelperAsync(['clean', key], (stdout, err) => {
            rowObj.btn.set_label(CATEGORIES[key].cleanAll === false ? 'Clean Separately' : 'Clean Category');
            
            if (err) {
                Main.notify('Space Cleaner', _(`Failed to clean ${CATEGORIES[key].label}: ${err.message}`));
                this._scanSystem();
                return;
            }

            try {
                let res = JSON.parse(stdout.trim());
                let freedBytes = res['freed'] || 0;
                Main.notify('Space Cleaner', _(`Successfully cleaned ${CATEGORIES[key].label}. Freed ${formatBytes(freedBytes)}.`));
            } catch (jsonErr) {
                Main.notify('Space Cleaner', _(`Cleaned ${CATEGORIES[key].label} successfully.`));
            }
            
            // Re-trigger scanning to refresh display values
            this._scanSystem();
        });
    }

    /**
     * Cleans all storage categories sequentially in a single operation.
     */
    _cleanAll() {
        this._refreshBtn.sensitive = false;
        this._cleanAllBtn.sensitive = false;
        this._summaryLabel.set_text(_('Cleaning all categories...'));

        this._runHelperAsync(['clean-all'], (stdout, err) => {
            this._refreshBtn.sensitive = true;
            this._cleanAllBtn.sensitive = true;

            if (err) {
                Main.notify('Space Cleaner', _(`Cleanup error: ${err.message}`));
                this._scanSystem();
                return;
            }

            try {
                let res = JSON.parse(stdout.trim());
                let totalFreed = res['freed'] || 0;
                let errors = res['errors'] || [];
                if (errors.length > 0)
                    Main.notify('Space Cleaner', _(`Clean All completed with ${errors.length} issue(s). Freed ${formatBytes(totalFreed)}.`));
                else
                    Main.notify('Space Cleaner', _(`All Clean All categories cleaned. Freed ${formatBytes(totalFreed)}.`));
            } catch (jsonErr) {
                Main.notify('Space Cleaner', _('System cleanup successfully completed.'));
            }

            // Re-trigger scanning to refresh display values
            this._scanSystem();
        });
    }
}
