# Copyright 2013-2017 Camptocamp SA
# © 2016 Sodexis
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import ast
import logging

from odoo import fields, models

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)


class OdooProductProduct(models.Model):
    _queue_priority = 4
    _name = "odoo.product.product"
    _inherit = "odoo.binding"
    _inherits = {"product.product": "odoo_id"}
    _description = "External Odoo Product"
    _sql_constraints = [
        (
            "external_id",
            "UNIQUE(external_id)",
            "External ID (external_id) must be unique!",
        ),
    ]

    def name_get(self):
        result = []
        for op in self:
            name = "{} (Backend: {})".format(
                op.odoo_id.display_name,
                op.backend_id.display_name,
            )
            result.append((op.id, name))
        return result

    RECOMPUTE_QTY_STEP = 1000  # products at a time

    def export_inventory(self, fields=None):
        """Export the inventory configuration and quantity of a product."""
        self.ensure_one()
        with self.backend_id.work_on(self._name) as work:
            exporter = work.component(usage="product.inventory.exporter")
            return exporter.run(self, fields)

    def resync(self):
        return self.delayed_import_record(self.backend_id, self.external_id, force=True)


class ProductProduct(models.Model):
    _inherit = "product.product"

    bind_ids = fields.One2many(
        comodel_name="odoo.product.product",
        inverse_name="odoo_id",
        string="Odoo Bindings",
    )

    def get_remote_qty_available(self, location=False):
        res = {}
        for product in self:
            context = {}
            bindings = product.bind_ids
            if not bindings:
                continue
            binding = bindings[0]
            res[product.id] = binding.execute_method(
                backend=binding.backend_id,
                model=self._name,
                method="get_quantity_website",
            )[0]
        return res


class ProductProductAdapter(Component):
    _name = "odoo.product.product.adapter"
    _inherit = "odoo.adapter"
    _apply_on = "odoo.product.product"

    _odoo_model = "product.product"

    # Set get_passive to True to get the passive records also.
    _get_passive = True

    def search(self, domain=None, model=None, offset=0, limit=None, order=None):
        """Search records according to some criteria
        and returns a list of ids
        :rtype: list
        """
        if domain is None:
            domain = []
        ext_filter = ast.literal_eval(
            str(self.backend_record.external_product_domain_filter)
        )
        domain += ext_filter
        return super(ProductProductAdapter, self).search(
            domain=domain, model=model, offset=offset, limit=limit, order=order
        )
