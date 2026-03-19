# -*- coding: utf-8 -*-
from odoo import models, SUPERUSER_ID
from odoo.exceptions import AccessError, UserError


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def button_mark_done(self):
        # Guard 1: only group_manufacturing_operator (Pratik, Prashant) may mark MOs done.
        # Superuser (uid=1) and sudo() environments bypass this so Odoo's own
        # test suite can call button_mark_done without hitting the access guard.
        if (
            not self.env.su
            and self.env.uid != SUPERUSER_ID
            and not self.env.user.has_group('elegomotors_setup.group_manufacturing_operator')
        ):
            raise AccessError('Only Manufacturing Operators can mark Manufacturing Orders as done.')

        # Guard 2: all linked Picking Slips (Raw Material) must be Done before
        # the MO can be finalised.  In 2-step manufacturing (pbm mode) Odoo
        # auto-creates one Picking Slip per MO confirmation linked via
        # production.picking_ids.  Pratik must wait for Amit to validate the
        # picking (EGO/Store → EGO/Production WIP) before producing.
        for production in self:
            pending = production.picking_ids.filtered(
                lambda p: p.state not in ('done', 'cancel')
            )
            if pending:
                names = ', '.join(pending.mapped('name'))
                raise UserError(
                    f'Please complete the Picking Slip (Raw Material) before finalising '
                    f'{production.name}.\nPending transfer(s): {names}'
                )

        return super().button_mark_done()
