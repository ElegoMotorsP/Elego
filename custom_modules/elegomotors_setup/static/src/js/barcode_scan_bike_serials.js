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
            onClose: this._onRefreshState.bind(this),
        });
    },
});
