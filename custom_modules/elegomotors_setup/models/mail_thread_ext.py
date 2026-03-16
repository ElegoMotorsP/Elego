from markupsafe import Markup
from odoo import models


class MailThreadElego(models.AbstractModel):
    """Adds _elego_post_note() so server-action safe_eval code can post
    formatted HTML chatter notes without needing ``Markup`` in scope.

    Odoo 18 does not expose ``Markup`` in the server-action eval context,
    so every CDATA block that calls ``message_post(body=Markup(...))`` raises
    NameError.  Centralising the Markup wrap here keeps all notification XML
    clean and consistent.
    """

    _inherit = "mail.thread"

    def _elego_post_note(self, body_html, partner_ids=None):
        """Post an HTML chatter note.  Called from server-action CDATA blocks.

        Args:
            body_html: plain HTML string (substitutions already applied by caller)
            partner_ids: list of res.partner ids to notify (optional)
        """
        self.message_post(
            body=Markup(body_html),
            message_type="notification",
            subtype_xmlid="mail.mt_note",
            partner_ids=partner_ids or [],
        )
