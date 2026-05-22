# -*- coding: utf-8 -*-
from odoo import api, models
import logging

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = 'res.company'

    @api.model
    def _try_set_inr_currency(self):
        """Set INR as the main company currency on first install.

        Called from noupdate="0" in company_config_data.xml so it runs on
        every upgrade, but silently no-ops when journal entries already exist
        (Odoo blocks currency changes on live databases with posted entries).
        """
        company = self.env.ref('base.main_company', raise_if_not_found=False)
        if not company:
            return
        inr = self.env.ref('base.INR', raise_if_not_found=False)
        if not inr or company.currency_id == inr:
            return
        try:
            company.write({'currency_id': inr.id})
        except Exception as e:
            _logger.info(
                'ElegoMotors: could not set INR currency (journal entries exist). '
                'Set it manually in Settings > General Settings. Error: %s', e
            )
