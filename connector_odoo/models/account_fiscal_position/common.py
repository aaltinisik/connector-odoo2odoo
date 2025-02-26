import logging

from odoo import fields, models

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)


class OdooAccountFiscalPosition(models.Model):
    _queue_priority = 5
    _name = "odoo.account.fiscal.position"
    _inherit = "odoo.binding"
    _inherits = {"account.fiscal.position": "odoo_id"}
    _description = "External Odoo Account Account"
    _sql_constraints = [
        (
            "external_id",
            "UNIQUE(external_id)",
            "External ID (external_id) must be unique!",
        ),
    ]

    def resync(self):
        if self.backend_id.main_record == "odoo":
            return self.delayed_export_record(self.backend_id)
        else:
            return self.delayed_import_record(
                self.backend_id, self.external_id, force=True
            )


class AccountFiscalPosition(models.Model):
    _inherit = "account.fiscal.position"

    bind_ids = fields.One2many(
        comodel_name="odoo.account.fiscal.position",
        inverse_name="odoo_id",
        string="Odoo Bindings",
    )


class AccountFiscalPositionAdapter(Component):
    _name = "odoo.account.fiscal.position.adapter"
    _inherit = "odoo.adapter"
    _apply_on = "odoo.account.fiscal.position"

    _odoo_model = "account.fiscal.position"

    # Set get_passive to True to get the passive records also.
    _get_passive = True


class AccountFiscalPositionListener(Component):
    _name = "account.fiscal.position.listener"
    _inherit = "base.connector.listener"
    _apply_on = ["account.fiscal.position"]
    _usage = "event.listener"
