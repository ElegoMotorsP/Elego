import { registry } from "@web/core/registry";
import { download } from "@web/core/network/download";
import { BlockUI } from "@web/core/ui/block_ui";
// vehicle tracking register.
registry.category("ir.actions.report handlers").add("veh_tracking_xlsx", async (action) => {
    if (action.report_type === 'veh_tracking_xlsx') {
        const blockUI = new BlockUI();
        await download({
            url: '/xlsx_reports',
            data: action.data,
            complete: () => unblockUI,
            error: (error) => self.call('crash_manager', 'rpc_error', error),
        });
    }
});
