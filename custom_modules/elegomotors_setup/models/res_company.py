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

    @api.model
    def _cleanup_lithium_fake_cells(self):
        """Retract a corrected mistake: an earlier version of
        battery_kit_data.xml wrongly decomposed the Lithium 60V30Ah/60V39Ah
        battery packs into invented "Li 12V30AH"/"Li 12V39AH" sub-cells via a
        phantom BOM. Lithium packs are sealed units sold/stocked as
        themselves — they were never built from smaller cells.

        Runs on every upgrade (noupdate="0"). On a database where the
        mistake was never deployed this is a no-op (the xmlids simply don't
        exist). Where it WAS deployed, the noupdate="1" data file no longer
        declaring these records does not auto-delete them, so this removes
        the phantom BOMs and, if unused elsewhere (no stock moves/POs
        referencing them), the fake cell products too.
        """
        bom_xmlids = [
            'elegomotors_setup.bom_kit_battery_li_60v30ah',
            'elegomotors_setup.bom_kit_battery_li_60v39ah',
        ]
        boms = self.env['mrp.bom']
        for xmlid in bom_xmlids:
            bom = self.env.ref(xmlid, raise_if_not_found=False)
            if bom:
                boms |= bom
        if boms:
            boms.bom_line_ids.unlink()
            boms.unlink()

        product_xmlids = [
            'elegomotors_setup.prod_cell_li_12v30ah',
            'elegomotors_setup.prod_cell_li_12v39ah',
        ]
        for xmlid in product_xmlids:
            product = self.env.ref(xmlid, raise_if_not_found=False)
            if not product:
                continue
            has_moves = bool(self.env['stock.move'].search_count(
                [('product_id', '=', product.id)]
            ))
            has_po_lines = bool(self.env['purchase.order.line'].search_count(
                [('product_id', '=', product.id)]
            ))
            if has_moves or has_po_lines:
                # Real transactions reference it — don't delete history,
                # just hide it from future use.
                product.write({'active': False, 'purchase_ok': False})
                _logger.info(
                    'ElegoMotors: %s has stock/purchase history — archived '
                    'instead of deleted.', product.display_name
                )
            else:
                product.unlink()
