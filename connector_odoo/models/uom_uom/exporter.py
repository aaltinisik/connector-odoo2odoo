# Copyright (C) 2020 Simplify Solutions. All Rights Reserved
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import logging

from odoo.tools.safe_eval import safe_eval

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)


class BatchUomExporter(Component):
    _name = "odoo.uom.uom.batch.exporter"
    _inherit = "odoo.delayed.batch.exporter"
    _apply_on = ["odoo.uom.uom"]
    _usage = "batch.exporter"

    def run(self, domain=None, force=False):
        loc_filter = safe_eval(self.backend_record.local_uom_uom_domain_filter)
        domain += loc_filter
        uoms = self.env["uom.uom"].search(domain)
        o_ids = self.env["odoo.uom.uom"].search(
            [
                ("backend_id", "=", self.backend_record.id),
            ]
        )
        _logger.info(
            "search for odoo UoM %s returned %s items",
            domain,
            len(o_ids),
        )
        o_uoms = self.env["uom.uom"].search(
            [("id", "in", [o.odoo_id.id for o in o_ids])]
        )
        to_bind = uoms - o_uoms
        for p in to_bind:
            self.env["odoo.uom.uom"].create(
                {
                    "odoo_id": p.id,
                    "external_id": 0,
                    "backend_id": self.backend_record.id,
                }
            )
        bind_ids = self.env["odoo.uom.uom"].search(
            [("odoo_id", "in", uoms.ids), ("backend_id", "=", self.backend_record.id)]
        )
        for uom in bind_ids:
            job_options = {
                "max_retries": 0,
            }
            self._export_record(uom, force=force)


class OdooUomExporter(Component):
    _name = "odoo.uom.uom.exporter"
    _inherit = "odoo.exporter"
    _apply_on = ["odoo.uom.uom"]
