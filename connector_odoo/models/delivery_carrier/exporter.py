# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)

import ast
import logging

from odoo.addons.component.core import Component
from odoo.addons.connector.components.mapper import mapping, only_create

_logger = logging.getLogger(__name__)


class BatchUserExporter(Component):
    _name = "odoo.delivery.carrier.batch.exporter"
    _inherit = "odoo.delayed.batch.exporter"
    _apply_on = ["odoo.delivery.carrier"]
    _usage = "batch.exporter"

    def run(self, domain=None, force=False):
        loc_filter = ast.literal_eval(self.backend_record.local_user_domain_filter)
        domain += loc_filter
        user_ids = self.env["delivery.carrier"].search(domain)

        o_ids = self.env["odoo.delivery.carrier"].search(
            [("backend_id", "=", self.backend_record.id)]
        )
        o_user_ids = self.env["delivery.carrier"].search(
            [("id", "in", [o.odoo_id.id for o in o_ids])]
        )
        to_bind = user_ids - o_user_ids

        for p in to_bind:
            self.env["odoo.delivery.carrier"].create(
                {
                    "odoo_id": p.id,
                    "external_id": 0,
                    "backend_id": self.backend_record.id,
                }
            )

        bind_ids = self.env["odoo.delivery.carrier"].search(
            [
                ("odoo_id", "in", [p.id for p in user_ids]),
                ("backend_id", "=", self.backend_record.id),
            ]
        )
        for carrier in bind_ids:
            self._export_record(carrier)


class OdooUserExporter(Component):
    _name = "odoo.delivery.carrier.exporter"
    _inherit = "odoo.exporter"
    _apply_on = ["odoo.delivery.carrier"]

    # def _export_dependencies(self):
    #     if not self.binding.parent_id:
    #         return
    #     parents = self.binding.parent_id.bind_ids
    #     parent = self.env["odoo.delivery.carrier"]

    #     if parents:
    #         parent = parents.filtered(
    #             lambda c: c.backend_id == self.backend_record
    #         )

    #         user = self.binder.to_external(parent, wrap=False)
    #         self._export_dependency(user, "odoo.delivery.carrier")

    def _create_data(self, map_record, fields=None, **kwargs):
        """Get the data to pass to :py:meth:`_create`"""
        datas = map_record.values(for_create=True, fields=fields, **kwargs)
        return datas


class UserExportMapper(Component):
    _name = "odoo.delivery.carrier.export.mapper"
    _inherit = "odoo.export.mapper"
    _apply_on = ["odoo.delivery.carrier"]

    direct = [
        ("name", "name"),
        ("login", "login"),
    ]

    def get_user_by_match_field(self, record):
        match_field = "login"
        domain = []

        domain = ast.literal_eval(self.backend_record.external_user_domain_filter)
        if record[match_field]:
            domain.append((match_field, "=", record[match_field]))
        domain.append("|")
        domain.append(("active", "=", False))
        domain.append(("active", "=", True))

        adapter = self.component(usage="record.exporter").backend_adapter
        user = adapter.search(domain)
        if len(user) == 1:
            return user[0]

        return False

    @only_create
    @mapping
    def odoo_id(self, record):
        external_id = self.get_user_by_match_field(record)

        if external_id:
            return {"external_id": external_id}
