odoo.define('vehicle_stock_dynamic_report_final.export_current_domain', function (require) {
    'use strict';
    const ListController = require('web.ListController');
    ListController.include({
        renderButtons: function () {
            this._super.apply(this, arguments);
            try {
                if (this.modelName !== 'vehicle.stock.report') return;
                if (!this.$buttons) return;
                if (!this.$buttons.find('.o_vehicle_export_domain').length) {
                    const self = this;
                    const $btn = $('<button type="button" class="btn btn-secondary o_vehicle_export_domain">Export view to XLSX</button>');
                    $btn.on('click', function () {
                        var domain = JSON.stringify(self.renderer.state ? self.renderer.state.domain : []);
                        var url = '/vehicle_stock_dynamic/export_xlsx?domain=' + encodeURIComponent(domain);
                        window.open(url, '_blank');
                    });
                    this.$buttons.append($btn);
                }
            } catch (e) {
                console.error('Export button init error', e);
            }
        },
    });
});
