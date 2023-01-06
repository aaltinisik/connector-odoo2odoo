# Copyright 2013-2017 Camptocamp SA
# © 2016 Sodexis
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)

import logging

from odoo.addons.component.core import Component
from odoo.addons.connector.components.mapper import mapping
from odoo.addons.connector.exception import MappingError

_logger = logging.getLogger(__name__)


class ProductTemplateBatchImporter(Component):
    """Import the Odoo Products Template.

    For every product category in the list, a delayed job is created.
    Import from a date
    """

    _name = "odoo.product.template.batch.importer"
    _inherit = "odoo.delayed.batch.importer"
    _apply_on = ["odoo.product.template"]

    def run(self, filters=None, force=False):
        """Run the synchronization"""

        external_ids = self.backend_adapter.search(filters)
        _logger.info(
            "search for odoo products template %s returned %s items",
            filters,
            len(external_ids),
        )
        for external_id in external_ids:
            # TODO : get the parent_left of the category so that we change
            #   the priority
            prod_id = self.backend_adapter.read(external_id)
            cat_id = self.backend_adapter.read(
                prod_id.categ_id.id, model="product.category"
            )
            job_options = {"priority": 15 + cat_id.parent_left or 0}
            self._import_record(external_id, job_options=job_options)


class ProductTemplateImportMapper(Component):
    _name = "odoo.product.template.import.mapper"
    _inherit = "odoo.import.mapper"
    _apply_on = ["odoo.product.template"]

    # TODO :     categ, special_price => minimal_price
    direct = [
        ("description", "description"),
        ("weight", "weight"),
        ("standard_price", "standard_price"),
        ("barcode", "barcode"),
        ("description_sale", "description_sale"),
        ("description_purchase", "description_purchase"),
        ("sale_ok", "sale_ok"),
        ("purchase_ok", "purchase_ok"),
        ("type", "detailed_type"),
        ("is_published", "is_published"),
        ("public_description", "public_description"),
    ]

    @mapping
    def company_id(self, record):
        return {"company_id": self.env.user.company_id.id}

    @mapping
    def uom_id(self, record):
        binder = self.binder_for("odoo.uom.uom")
        uom = binder.to_internal(record.uom_id.id, unwrap=True)
        return {"uom_id": uom.id, "uom_po_id": uom.id}

    # @mapping # Todo: we don't use pricing at template level
    # def price(self, record):
    #     return {"list_price": record.list_price}

    @mapping
    def default_code(self, record):
        if not hasattr(record, "default_code"):
            return {}
        code = record["default_code"]
        if not code:
            return {"default_code": "/"}
        return {"default_code": code}

    @mapping
    def name(self, record):
        if not hasattr(record, "name"):
            return {}
        name = record["name"]
        if not name:
            return {"name": "/"}
        return {"name": name}

    @mapping
    def category(self, record):
        categ_id = record["categ_id"]
        binder = self.binder_for("odoo.product.category")

        cat = binder.to_internal(categ_id.id, unwrap=True)
        if not cat:
            raise MappingError(
                "Can't find external category with odoo_id %s." % categ_id.odoo_id
            )
        return {"categ_id": cat.id}

    @mapping
    def attribute_line_ids(self, record):
        res = {"attribute_line_ids": []}
        attr_line_ids = record.attribute_line_ids
        if self.backend_record.work_with_variants and attr_line_ids:
            for attr_line in attr_line_ids:
                val_list = []
                attr_id = self.binder_for("odoo.product.attribute").to_internal(
                    attr_line.attribute_id.id, unwrap=True
                )
                for value in attr_line.value_ids:
                    attr_val = self.binder_for(
                        "odoo.product.attribute.value"
                    ).to_internal(value.id, unwrap=True)
                    if attr_val:
                        val_list.append(attr_val.id)
                    else:
                        raise MappingError(
                            "Can't find external attribute value %s with"
                            " odoo_id %s. Sync the attributes first"
                            % (value.name, value.odoo_id)
                        )
                res["attribute_line_ids"].append(
                    (
                        0,
                        0,
                        {"attribute_id": attr_id.id, "value_ids": [(6, 0, val_list)]},
                    )
                )
        return res

    @mapping
    def feature_line_ids(self, record):
        # TODO: BU VE ATTRIBUTE LINE DUPLICATE OLUYOR ONU ÇÖZMEN LAZIM
        res = {"feature_line_ids": []}
        feature_lines = record.feature_line_ids
        if self.backend_record.work_with_variants and feature_lines:
            for feature_line in feature_lines:
                val_list = []
                feature_id = self.binder_for("odoo.product.attribute").to_internal(
                    feature_line.feature_id.id, unwrap=True
                )
                for value in feature_line.value_ids:
                    feature_val = self.binder_for(
                        "odoo.product.attribute.value"
                    ).to_internal(value.id, unwrap=True)
                    if feature_val:
                        val_list.append(feature_val.id)
                    else:
                        raise MappingError(
                            "Can't find external attribute value %s with"
                            " odoo_id %s. Sync the attributes first"
                            % (value.name, value.odoo_id)
                        )
                res["feature_line_ids"].append(
                    (
                        0,
                        0,
                        {"feature_id": feature_id.id, "value_ids": [(6, 0, val_list)]},
                    )
                )
        return res

    @mapping
    def image(self, record):
        if self.backend_record.version in (
            "6.1",
            "7.0",
            "8.0",
            "9.0",
            "10.0",
            "11.0",
            "12.0",
        ):
            return {"image_1920": record.image_medium if hasattr(record, "image_medium") else False}
        else:
            return {"image_1920": record.image_1920}


class ProductTemplateImporter(Component):
    _name = "odoo.product.template.importer"
    _inherit = "odoo.importer"
    _apply_on = ["odoo.product.template"]

    # def _before_import(self):
    #     """Import attachments before product.template we can do
    #     mapping on web attachments"""
    #     web_attachs = self.odoo_record.website_attachment_ids
    #     if web_attachs:
    #         self.env["odoo.ir.attachment"].with_delay().import_batch(
    #             self.backend_record, [('id', 'in', web_attachs.ids)]
    #         )
    #     super(ProductTemplateImporter, self)._before_import()

    def _import_dependencies(self, force=False):
        """Import the dependencies for the record"""
        uom_id = self.odoo_record.uom_id
        self._import_dependency(uom_id.id, "odoo.uom.uom", force=force)

        categ_id = self.odoo_record.categ_id
        self._import_dependency(categ_id.id, "odoo.product.category", force=force)
        return super()._import_dependencies(force=force)

    def _get_context(self, data):
        """Context for the create-write"""
        return {"no_handle_variant": False}  # Todo : check if it's needed

    def _after_import(self, binding, force=False):
        imported_template = self.binder.to_internal(self.external_id)
        if imported_template:
            self._import_website_images()
            self._import_website_attachments(imported_template)

        super(ProductTemplateImporter, self)._after_import(binding, force=force)

    def _import_website_attachments(self, tmpl_id):
        attachment_ids = self.odoo_record.website_attachment_ids
        if attachment_ids:
            for attachment_id in attachment_ids:
                self.env["odoo.ir.attachment"].with_delay().import_record(
                    self.backend_record, attachment_id.id
                )
            imported_attachments = self.env["ir.attachment"].search(
                [
                    ("bind_ids.external_id", "in", attachment_ids.ids),
                    ("res_model", "=", "product.template"),
                ]
            )
            tmpl_id.write(
                {
                    "website_attachment_ids": [(6, 0, imported_attachments.ids)],
                }
            )
        return True

    def _import_website_images(self):
        image_ids = self.odoo_record.image_ids
        if image_ids:
            for image_id in image_ids:
                self.env["odoo.product.image"].with_delay().import_record(
                    self.backend_record, image_id.id
                )
                # Todo: imageların hepsi import olmuyor.
        return True
