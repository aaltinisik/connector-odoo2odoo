# © 2013 Guewen Baconnier,Camptocamp SA,Akretion
# © 2016 Sodexis
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
from contextlib import contextmanager
from datetime import datetime
import psycopg2

import odoo
from odoo import _

from odoo.addons.component.core import AbstractComponent
from odoo.addons.connector.exception import IDMissingInBackend, RetryableJobError

_logger = logging.getLogger(__name__)

# Exporters for Odoo.

# In addition to its export job, an exporter has to:

# * check in Odoo if the record has been updated more recently than the
#   last sync date and if yes, delay an import
# * call the ``bind`` method of the binder to update the last sync date


class OdooBaseExporter(AbstractComponent):
    """Base exporter for Odoo"""

    _name = "odoo.base.exporter"
    _inherit = ["base.exporter", "base.odoo.connector"]
    _usage = "record.exporter"

    def __init__(self, working_context):
        super(OdooBaseExporter, self).__init__(working_context)
        self.binding = None
        self.external_id = None

    def _must_skip(self):
        """Base method to check if the export should be skipped."""
        return False

    def _after_export(self):
        """Can do several actions after exporting a record on odoo"""
        return True

    def _delay_import(self):
        """Schedule an import of the record.

        Adapt in the sub-classes when the model is not imported
        using ``import_record``.
        """
        # force is True because the sync_date will be more recent
        # so the import would be skipped
        assert self.external_id
        self.binding.delayed_import_record(
            self.backend_record, self.external_id, force=False
        )

    def _should_import(self):
        """Before the export, compare the update date
        in Odoo and the last sync date in Odoo,
        if the former is more recent, schedule an import
        to not miss changes done in Odoo.
        """
        assert self.binding
        if not self.external_id:
            return False
        sync = self.binding.sync_date
        if not sync:
            return True
        record = self.backend_adapter.read(self.external_id)
        if not record.get("write_date"):
            # in rare case it can be empty, in doubt, import it
            return True
        sync_date = odoo.fields.Datetime.from_string(sync)
        odoo_date = datetime.strptime(record["write_date"], "%Y-%m-%d %H:%M:%S")
        return sync_date < odoo_date

    def run(self, binding, *args, **kwargs):
        """Run the synchronization
        :param binding: binding record to export
        """
        if self.backend_record.no_export:
            return _("Nothing to export. (no export flag on connector)")

        self.binding = binding
        self.external_id = self.binder.to_external(self.binding, wrap=False)

        if self._must_skip():
            return _("Export skipped.")

        try:
            should_import = self._should_import()
        except IDMissingInBackend:
            self.external_id = None
            should_import = False
        if should_import:
            self._delay_import()
        result = self._run(*args, **kwargs)

        self.binder.bind(self.external_id, self.binding)
        # Commit so we keep the external ID when there are several
        # exports (due to dependencies) and one of them fails.
        # The commit will also release the lock acquired on the binding
        # record
        if not odoo.tools.config["test_enable"]:
            self.env.cr.commit()  # pylint: disable=invalid-commit
        self._after_export()
        return result


class BatchExporter(AbstractComponent):
    """The role of a BatchExporter is to search for a list of
    items to export, then it can either export them directly or delay
    the export of each item separately.
    """

    _name = "odoo.batch.exporter"
    _inherit = ["base.exporter", "base.odoo.connector"]
    _usage = "batch.exporter"

    def run(self, domain=None, force=False):
        """Run the synchronization"""
        record_ids = self.backend_adapter.search(domain)
        for record_id in record_ids:
            self._export_record(record_id)


class DelayedBatchExporter(AbstractComponent):
    """Delay import of the records"""

    _name = "odoo.delayed.batch.exporter"
    _inherit = "odoo.batch.exporter"

    def _export_record(self, external_id, job_options=None, **kwargs):
        """Delay the import of the records"""
        delayable = external_id.with_delay(
            channel=self.model._unique_channel_name,
            priority=self.model._priority,
            **job_options or {},
        )
        delayable.export_record(self.backend_record, **kwargs)


class DirectBatchExporter(AbstractComponent):
    """Import the records directly, without delaying the jobs."""

    _name = "odoo.direct.batch.exporter"
    _inherit = "odoo.batch.exporter"

    def _export_record(self, external_id):
        """Import the record directly"""
        self.model.export_record(self.backend_record, external_id)


class OdooExporter(AbstractComponent):
    """A common flow for the exports to Odoo"""

    _name = "odoo.exporter"
    _inherit = "odoo.base.exporter"

    def __init__(self, working_context):
        super(OdooExporter, self).__init__(working_context)
        self.binding = None
        self.job_uuid = None

    def _connect_with_job(self, context_dict):
        """Save job_uuid in context to match write external odoo id to the job"""
        if job_uuid := context_dict.get("job_uuid"):
            self.job_uuid = job_uuid
        return True

    def _lock(self):
        """Lock the binding record.
        Lock the binding record so we are sure that only one export
        job is running for this record if concurrent jobs have to export the
        same record.
        When concurrent jobs try to export the same record, the first one
        will lock and proceed, the others will fail to lock and will be
        retried later.
        This behavior works also when the export becomes multilevel
        with :meth:`_export_dependencies`. Each level will set its own lock
        on the binding record it has to export.
        """
        sql = "SELECT id FROM %s WHERE ID = %%s FOR UPDATE NOWAIT" % self.model._table
        try:
            self.env.cr.execute(sql, (self.binding.id,), log_exceptions=False)
        except psycopg2.OperationalError as err:
            _logger.info(
                "A concurrent job is already exporting the same "
                "record (%s with id %s). Job delayed later.",
                self.model._name,
                self.binding.id,
            )
            raise RetryableJobError(
                "Could not optain lock %s (%s): \n%s"
                % (self.model._name, self.binding.id, str(err)),
                seconds=5,
            )

    def _link_queue_job(self, binding):
        # Add relation between job and binding, so we can monitor the process
        if binding and self.job_uuid:
            job_id = self.env["queue.job"].search([("uuid", "=", self.job_uuid)])
            if job_id:
                job_id.write(
                    {
                        "odoo_binding_model_name": binding.odoo_id._name,
                        "odoo_binding_id": binding.odoo_id.id,
                    }
                )
                self.env.cr.commit()  # Commit in case of a failure in the next steps

    @contextmanager
    def _retry_unique_violation(self):
        """Context manager: catch Unique constraint error and retry the
        job later.

        When we execute several jobs workers concurrently, it happens
        that 2 jobs are creating the same record at the same time (binding
        record created by :meth:`_export_dependency`), resulting in:

            IntegrityError: duplicate key value violates unique
            constraint "odoo_product_product_odoo_uniq"
            DETAIL:  Key (backend_id, odoo_id)=(1, 4851) already exists.

        In that case, we'll retry the import just later.

        .. warning:: The unique constraint must be created on the
                     binding record to prevent 2 bindings to be created
                     for the same Odoo record.
        """
        try:
            yield
        except psycopg2.IntegrityError as err:
            if err.pgcode == psycopg2.errorcodes.UNIQUE_VIOLATION:
                raise RetryableJobError(
                    "Database error occured when exporting %s (%s): \n%s"
                    % (self.model._name, self.binding.id, str(err)),
                    seconds=5,
                )
            else:
                raise Exception from err

    def _export_dependency(
        self,
        relation,
        binding_model,
        component_usage="record.exporter",
        binding_field="bind_ids",
        binding_extra_vals=None,
    ):
        """
        Export a dependency. The exporter class is a subclass of
        ``OdooExporter``. If a more precise class need to be defined,
        it can be passed to the ``exporter_class`` keyword argument.

        .. warning:: a commit is done at the end of the export of each
                     dependency. The reason for that is that we pushed a record
                     on the backend and we absolutely have to keep its ID.

                     So you *must* take care not to modify the Odoo
                     database during an export, excepted when writing
                     back the external ID or eventually to store
                     external data that we have to keep on this side.

                     You should call this method only at the beginning
                     of the exporter synchronization,
                     in :meth:`~._export_dependencies`.

        :param relation: record to export if not already exported
        :type relation: :py:class:`odoo.models.BaseModel`
        :param binding_model: name of the binding model for the relation
        :type binding_model: str | unicode
        :param component_usage: 'usage' to look for to find the Component to
                                for the export, by default 'record.exporter'
        :type exporter: str | unicode
        :param binding_field: name of the one2many field on a normal
                              record that points to the binding record
                              (default: odoo_bind_ids).
                              It is used only when the relation is not
                              a binding but is a normal record.
        :type binding_field: str | unicode
        :binding_extra_vals:  In case we want to create a new binding
                              pass extra values for this binding
        :type binding_extra_vals: dict
        """
        if not relation:
            return
        rel_binder = self.binder_for(binding_model)
        # wrap is typically True if the relation is for instance a
        # 'product.product' record but the binding model is
        # 'odoo.product.product'
        wrap = relation._name != binding_model

        if wrap and hasattr(relation, binding_field):
            if rel_binder and hasattr(rel_binder.model, "active"):
                binding = self.env[binding_model].search(
                    [
                        ("odoo_id", "=", relation.id),
                        "|",
                        ("active", "=", False),
                        ("active", "=", True),
                    ],
                )
            else:
                binding = relation[binding_field]
            if binding:
                assert len(binding) == 1, (
                    "only 1 binding for a backend is " "supported in _export_dependency"
                )
            # we are working with a unwrapped record (e.g.
            # product.category) and the binding does not exist yet.
            # Example: I created a product.product and its binding
            # odoo.product.product and we are exporting it, but we need to
            # create the binding for the product.category on which it
            # depends.
            else:
                bind_values = {
                    "backend_id": self.backend_record.id,
                    "odoo_id": relation.id,
                }
                if binding_extra_vals:
                    bind_values.update(binding_extra_vals)
                # If 2 jobs create it at the same time, retry
                # one later. A unique constraint (backend_id,
                # odoo_id) should exist on the binding model
                with self._retry_unique_violation():
                    binding = (
                        self.env[binding_model]
                        .with_context(connector_no_export=True)
                        .sudo()
                        .create(bind_values)
                    )
                    # Eager commit to avoid having 2 jobs
                    # exporting at the same time. The constraint
                    # will pop if an other job already created
                    # the same binding. It will be caught and
                    # raise a RetryableJobError.
                    if not odoo.tools.config["test_enable"]:
                        self.env.cr.commit()  # pylint: disable=invalid-commit
        else:
            # If odoo_bind_ids does not exist we are typically in a
            # "direct" binding (the binding record is the same record).
            # If wrap is True, relation is already a binding record.
            binding = relation

        exporter = self.component(usage=component_usage, model_name=binding_model)
        exporter.run(binding)
        return True

    def _export_dependencies(self):
        """Export the dependencies for the record"""
        return

    def _get_external_id_with_data(self):
        """
        Search for an external ID with the data of the record.
        """
        return

    def _before_export(self):
        """Hook called before the export"""
        return

    def _map_data(self):
        """Returns an instance of
        :py:class:`~odoo.addons.connector.components.mapper.MapRecord`
        """
        return self.mapper.map_record(self.binding)

    def _create_data(self, map_record, fields=None, **kwargs):
        """Get the data to pass to :py:meth:`_create`"""
        # datas = ast.literal_eval(
        #  self.backend_record.default_product_export_dict)
        cp_datas = map_record.values(for_create=True, fields=fields, **kwargs)
        # Combine default values with the computed ones
        #  datas.update(cp_datas)
        return cp_datas

    def _create(self, data):
        """Create the Odoo record"""
        return self.backend_adapter.create(data)

    def _update_data(self, map_record, fields=None, **kwargs):
        """Get the data to pass to :py:meth:`_update`"""
        return map_record.values(fields=fields, **kwargs)

    def _update(self, data):
        """Update an Odoo record"""
        assert self.external_id
        self.backend_adapter.write(self.external_id, data)

    def _run(self, fields=None):
        """Flow of the synchronization, implemented in inherited classes"""
        assert self.binding

        if not self.external_id:
            fields = None  # should be created with all the fields

        # Add relation between job and binding, so we can monitor the process
        # self._link_queue_job(self.binding)

        # run some logic before the export
        self._before_export()

        # export the missing linked resources
        self._export_dependencies()

        # prevent other jobs to export the same record
        # will be released on commit (or rollback)
        self._lock()

        # try to match with data if no external id
        if not self.external_id:
            self._get_external_id_with_data()

        map_record = self._map_data()

        # 0 is a special value for external_id, it means that the
        # record is not yet exported
        if self.external_id and self.external_id != 0:
            record = self._update_data(map_record, fields=fields)
            if not record:
                return _("Nothing to export.")
            self._update(record)
        else:
            record = self._create_data(map_record, fields=fields)
            if not record:
                return _("Nothing to export.")
            if "external_id" in record and record["external_id"]:
                self.external_id = record["external_id"]
            else:
                self.external_id = self._create(record)
        return _("Record exported with ID %s on Odoo.") % self.external_id
