# © 2013 Guewen Baconnier,Camptocamp SA,Akretion
# © 2016 Sodexis
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo.addons.component.core import AbstractComponent
from odoo.addons.connector.components.mapper import external_to_m2o, mapping


def field_by_lang(field):
    """``field`` is the name of the source field.

    Naming the arg: ``field`` is required for the conversion"""

    def modifier(self, record, to_attr):
        """self is the current Mapper,
        record is the current record to map,
        to_attr is the target field"""
        lang_code = self.backend_record.get_default_language_code()
        rec_lang = record.with_context(lang=lang_code)
        return rec_lang[field]

    return modifier


class OdooImportMapper(AbstractComponent):
    _name = "odoo.import.mapper"
    _inherit = ["base.odoo.connector", "base.import.mapper"]
    _usage = "import.mapper"

    @mapping
    def odoo_id(self, record):
        """Value is assigned to odoo_id so as not to duplicate records already imported"""
        model_id = record["id"]
        binder = self.binder_for()
        res_id = binder.to_internal(model_id, unwrap=True)

        # If the record is not found with traditional way,
        # We try to get it with `_get_binding_with_data` method.
        if not res_id and self.options.get("binding"):
            res_id = self.options["binding"].odoo_id

        return {"odoo_id": res_id.id if res_id else None}

    @mapping
    def backend_id(self, record):
        return {"backend_id": self.backend_record.id}

    def _map_direct(self, record, from_attr, to_attr):
        """Apply the ``direct`` mappings.
        :param record: record to convert from a source to a target
        :param from_attr: name of the source attribute or a callable
        :type from_attr: callable | str
        :param to_attr: name of the target attribute
        :type to_attr: str
        yigit 26.07.2023: this method is changed to work with new odoo connector
        """
        return record.get(from_attr, False)
        # if callable(from_attr):
        #     return from_attr(self, record, to_attr)
        # value = record[from_attr] if hasattr(record, from_attr) else False
        # if not value:
        #     return False

        # Backward compatibility: when a field is a relation, and a modifier is
        # not used, we assume that the relation model is a binding.
        # Use an explicit modifier external_to_m2o in the 'direct' mappings to
        # change that.
        field = self.model._fields[to_attr] if to_attr in self.model._fields else None
        if field and field.type == "many2one":
            mapping_func = external_to_m2o(from_attr)
            value = mapping_func(self, record, to_attr)
        return value


class OdooExportMapper(AbstractComponent):
    _name = "odoo.export.mapper"
    _inherit = ["base.odoo.connector", "base.export.mapper"]
    _usage = "export.mapper"


# class OdooExportChildMapper(AbstractComponent):
#     _name = "odoo.child.export"
#     _inherit = ["base.odoo.connector", "base.map.child"]
#     _usage = "export.map.child"
