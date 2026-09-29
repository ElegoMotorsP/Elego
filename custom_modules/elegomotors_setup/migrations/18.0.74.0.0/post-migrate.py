# -*- coding: utf-8 -*-
"""Freeze data/users_data.xml's 7 user records so future upgrades stop
resetting their groups_id.

Before this version, users_data.xml's <data> block was noupdate="0", so
every `-u elegomotors_setup` force-reset every department user's groups to
exactly what's written in that file, silently undoing any permission change
made via Settings > Users (or the new Access Matrix). The XML file itself
now says noupdate="1", but that only controls what happens the first time an
ir.model.data row is created — it does NOT retroactively change the
noupdate flag Odoo already stored for these 7 users back when they were
first installed. This one-time migration flips that stored flag directly so
the new noupdate="1" in the XML actually takes effect on production.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE ir_model_data
           SET noupdate = true
         WHERE module = 'elegomotors_setup'
           AND model = 'res.users'
    """)
