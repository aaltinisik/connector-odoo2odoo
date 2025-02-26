# Copyright 2013-2017 Camptocamp SA
# © 2016 Sodexis
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)

from odoo import fields, models

from odoo.addons.component.core import Component


class OdooProductAttribute(models.Model):
    _queue_priority = 7
    _name = "odoo.product.attribute"
    _inherit = ["odoo.binding"]
    _inherits = {"product.attribute": "odoo_id"}
    _description = "Odoo Product Attribute"
    _sql_constraints = [
        (
            "external_id",
            "UNIQUE(external_id)",
            "External ID (external_id) must be unique!",
        ),
    ]

    def resync(self):
        return self.delayed_import_record(self.backend_id, self.external_id, force=True)


class ProductAttribute(models.Model):
    _inherit = "product.attribute"

    bind_ids = fields.One2many(
        comodel_name="odoo.product.attribute",
        inverse_name="odoo_id",
        string="Odoo Bindings",
    )


class ProductAttributeAdapter(Component):
    _name = "odoo.product.attribute.adapter"
    _inherit = "odoo.adapter"
    _apply_on = "odoo.product.attribute"

    _odoo_model = "product.attribute"

    # Set get_passive to True to get the passive records also.
    _get_passive = False
