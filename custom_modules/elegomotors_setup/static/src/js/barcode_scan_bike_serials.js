/** @odoo-module **/

import MainComponent from '@stock_barcode/components/main';
import { patch } from '@web/core/utils/patch';
import { user } from '@web/core/user';
import { onWillStart } from '@odoo/owl';

/**
 * Adds bike-serial scanning to the Barcode app's outgoing-delivery screen.
 *
 * Two ways to assign a bike serial to a delivery, both calling the exact
 * same server-side validation (model/colour match, Finished-Goods
 * availability, QC blacklist, duplicate-delivery check):
 *
 *  1. Scan directly on the picking's own scan screen — the primary flow.
 *     Every scan (camera or hardware scanner) arrives through
 *     onBarcodeScanned, the single entry point the whole Barcode app uses
 *     for all scan sources. It's patched to try
 *     stock_picking.action_scan_bike_serial() first; if the barcode isn't a
 *     recognised bike serial at all, it falls through to Odoo's normal
 *     product-scan handling unchanged.
 *  2. "Scan Bike Serials" button — opens the existing delivery bike scan
 *     wizard for manual serial entry, kept as a fallback for when a
 *     barcode can't be scanned (damaged print, etc).
 */
patch(MainComponent.prototype, {
    setup() {
        super.setup();
        this.state.canScanBikeSerials = false;
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
        this.action.doAction(action, {
            onClose: () => this._onRefreshState(),
        });
    },

    _isOutgoingDeliveryScreen() {
        return this.resModel === 'stock.picking'
            && this.env.model.record
            && this.env.model.record.picking_type_code === 'outgoing';
    },

    onBarcodeScanned(barcode) {
        if (this._isOutgoingDeliveryScreen() && barcode) {
            this.actionMutex.exec(() => this._tryScanBikeSerial(barcode));
            return;
        }
        return super.onBarcodeScanned(barcode);
    },

    /**
     * Tries the scan as a bike serial first. If the server doesn't
     * recognise it as one at all, falls back to Odoo's normal barcode
     * handling — calling env.model.processBarcode() directly rather than
     * re-entering onBarcodeScanned/super.onBarcodeScanned, since we're
     * already running inside actionMutex.exec() here and re-wrapping in
     * another actionMutex.exec() would deadlock against this still-running
     * task.
     */
    async _tryScanBikeSerial(barcode) {
        const result = await this.orm.call(
            this.resModel,
            'action_scan_bike_serial',
            [[this.resId], barcode],
        );
        if (!result.handled) {
            await this.env.model.processBarcode(barcode);
            if ('vibrate' in window.navigator) {
                window.navigator.vibrate(100);
            }
            return;
        }
        this.notification.add(result.message, {
            type: result.success ? 'success' : 'warning',
        });
        if (result.success) {
            await this._onRefreshState();
        }
    },
});
