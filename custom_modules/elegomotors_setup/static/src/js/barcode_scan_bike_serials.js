/** @odoo-module **/

import MainComponent from '@stock_barcode/components/main';
import { patch } from '@web/core/utils/patch';
import { user } from '@web/core/user';
import { onWillStart } from '@odoo/owl';

/**
 * Adds "Scan Bike Serials" to the Barcode app's outgoing-delivery screen.
 * Reuses the same wizard and server-side validation the web backend's
 * header button already calls — stock_picking.action_open_delivery_bike_scan_wizard()
 * — so a store/permissioned user on mobile gets the identical model/colour,
 * Finished-Goods, blacklist and duplicate-delivery checks as the web UI.
 *
 * While the wizard dialog is open, every scan (camera or hardware scanner)
 * still arrives through MainComponent.onBarcodeScanned() — that's the single
 * entry point the whole Barcode app uses for all scan sources, dialog open
 * or not. Left alone, the underlying picking screen would swallow the scan
 * as a generic product scan before it ever reached the wizard's own text
 * field. So onBarcodeScanned is patched to redirect scans into the open
 * wizard instead, routing each one to the row for the model it actually
 * belongs to (looked up by serial), not just "whichever row is selected" —
 * so bikes of different models can be scanned in any order.
 */
patch(MainComponent.prototype, {
    setup() {
        super.setup();
        this.state.canScanBikeSerials = false;
        this.state.bikeScanWizardOpen = false;
        onWillStart(async () => {
            this.state.canScanBikeSerials = (
                await user.hasGroup('elegomotors_setup.group_inbound_operator')
            ) || (
                await user.hasGroup('base.group_erp_manager')
            );
        });
    },

    async scanBikeSerials(ev) {
        ev.stopPropagation();
        await this.env.model.save();
        const action = await this.orm.call(
            this.resModel,
            'action_open_delivery_bike_scan_wizard',
            [[this.resId]],
        );
        this.state.bikeScanWizardOpen = true;
        this.action.doAction(action, {
            onClose: () => {
                this.state.bikeScanWizardOpen = false;
                this._onRefreshState();
            },
        });
    },

    onBarcodeScanned(barcode) {
        // TEMP DEBUG — remove once the mobile scan-routing issue is confirmed fixed.
        this.notification.add(
            `[dbg] onBarcodeScanned "${barcode}" wizardOpen=${this.state.bikeScanWizardOpen}`,
            { type: 'info', sticky: true },
        );
        if (this.state.bikeScanWizardOpen && barcode) {
            this.actionMutex.exec(() => this._feedBikeScanWizard(barcode));
            return;
        }
        return super.onBarcodeScanned(barcode);
    },

    _getBikeScanDialog() {
        return Array.from(document.querySelectorAll('.o_dialog'))
            .find((dialog) => dialog.querySelector('[name="scanned_serial"]')) || null;
    },

    /**
     * Places a scanned barcode into the "Scan Bike Serials" wizard: looks up
     * which product the serial actually belongs to, and fills the first
     * empty row for that exact model. Falls back to the currently selected
     * (or first empty) row when the serial isn't recognised, so the
     * wizard's own validation still shows its normal "not found" message.
     */
    async _feedBikeScanWizard(barcode) {
        const dialog = this._getBikeScanDialog();
        // TEMP DEBUG — remove once the mobile scan-routing issue is confirmed fixed.
        this.notification.add(`[dbg] dialog found=${!!dialog}`, { type: 'info', sticky: true });
        if (!dialog) {
            return;
        }

        const lots = await this.orm.searchRead(
            'stock.lot',
            [['name', '=', barcode]],
            ['product_id'],
        );
        const productName = lots[0]?.product_id?.[1];
        // TEMP DEBUG — remove once the mobile scan-routing issue is confirmed fixed.
        this.notification.add(
            `[dbg] lot lookup for "${barcode}" -> product="${productName}"`,
            { type: 'info', sticky: true },
        );

        const rows = Array.from(dialog.querySelectorAll('.o_data_row'));
        const isRowEmpty = (row) => {
            const cell = row.querySelector('[name="scanned_serial"]');
            if (!cell) {
                return false;
            }
            const input = cell.querySelector('input');
            return !cell.textContent.trim() && !(input && input.value);
        };

        let targetCell = null;
        if (productName) {
            const modelRow = rows.find((row) => {
                const modelCell = row.querySelector('[name="product_display"]');
                return modelCell && modelCell.textContent.trim() === productName && isRowEmpty(row);
            });
            targetCell = modelRow && modelRow.querySelector('[name="scanned_serial"]');
        }
        if (!targetCell) {
            targetCell = dialog.querySelector('.o_selected_row [name="scanned_serial"]');
        }
        if (!targetCell) {
            const emptyRow = rows.find(isRowEmpty);
            targetCell = emptyRow && emptyRow.querySelector('[name="scanned_serial"]');
        }
        // TEMP DEBUG — remove once the mobile scan-routing issue is confirmed fixed.
        this.notification.add(`[dbg] targetCell found=${!!targetCell}, rows=${rows.length}`, { type: 'info', sticky: true });
        if (!targetCell) {
            return;
        }

        if (!targetCell.querySelector('input')) {
            targetCell.click();
            await new Promise((resolve) => setTimeout(resolve, 120));
        }
        const input = dialog.querySelector('.o_selected_row [name="scanned_serial"] input')
            || targetCell.querySelector('input');
        // TEMP DEBUG — remove once the mobile scan-routing issue is confirmed fixed.
        this.notification.add(`[dbg] input found=${!!input}`, { type: 'info', sticky: true });
        if (!input) {
            return;
        }
        input.focus();
        input.value = barcode;
        input.dispatchEvent(new Event('input', { bubbles: true }));
    },
});
