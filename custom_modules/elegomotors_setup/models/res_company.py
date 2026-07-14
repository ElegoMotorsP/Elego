# -*- coding: utf-8 -*-
from odoo import api, models
import logging

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = 'res.company'

    @api.model
    def _try_set_inr_currency(self):
        """Force INR as the currency everywhere. Runs on every upgrade
        (called from noupdate="0" in company_config_data.xml). Idempotent.

        1. Activate INR, set it as the main company currency. Odoo refuses
           the ORM write once journal entries exist, so on live databases we
           fall back to a direct SQL update — amounts are NOT converted,
           only relabeled (the figures were always INR-intended; the company
           was simply created with USD defaults).
        2. Repoint every pricelist to INR (this is what the "Default (USD)"
           pricelist on quotations comes from) and fix USD in their names.
        3. Deactivate USD so it no longer appears in dropdowns. Historical
           documents that reference USD still render fine.
        """
        company = self.env.ref('base.main_company', raise_if_not_found=False)
        inr = self.env.ref('base.INR', raise_if_not_found=False)
        if not company or not inr:
            return

        if not inr.active:
            inr.active = True

        if company.currency_id != inr:
            try:
                company.write({'currency_id': inr.id})
            except Exception as e:
                _logger.warning(
                    'ElegoMotors: ORM refused the currency change (journal '
                    'entries exist) — forcing INR via SQL without amount '
                    'conversion. Original error: %s', e
                )
                self.env.cr.execute(
                    'UPDATE res_company SET currency_id = %s WHERE id = %s',
                    (inr.id, company.id),
                )
                company.invalidate_recordset(['currency_id'])

        # Repoint all pricelists (incl. archived) to INR. sale.order.currency_id
        # is related to the pricelist currency, so existing quotations pick
        # this up automatically.
        pricelists = self.env['product.pricelist'].with_context(
            active_test=False
        ).search([('currency_id', '!=', inr.id)])
        for pricelist in pricelists:
            vals = {'currency_id': inr.id}
            if pricelist.name and 'USD' in pricelist.name:
                vals['name'] = pricelist.name.replace('USD', 'INR')
            pricelist.write(vals)

        # Hide USD from all currency dropdowns going forward.
        usd = self.env.ref('base.USD', raise_if_not_found=False)
        if usd and usd.active and company.currency_id == inr:
            try:
                usd.active = False
            except Exception as e:
                _logger.info('ElegoMotors: could not deactivate USD: %s', e)
