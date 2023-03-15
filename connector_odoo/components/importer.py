# © 2013 Guewen Baconnier,Camptocamp SA,Akretion
# © 2016 Sodexis
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

"""

Importers for Odoo.

An import can be skipped if the last sync date is more recent than
the last update in Odoo.

They should call the ``bind`` method if the binder even if the records
are already bound, to update the last sync date.

"""

import logging

from odoo import _, fields

from odoo.addons.component.core import AbstractComponent
from odoo.addons.connector.exception import IDMissingInBackend
from odoo.addons.queue_job.exception import NothingToDoJob

_logger = logging.getLogger(__name__)


class OdooImporter(AbstractComponent):
    """Base importer for Odoo"""

    _name = "odoo.importer"
    _inherit = ["base.importer", "base.odoo.connector"]
    _usage = "record.importer"

    def __init__(self, work_context):
        super(OdooImporter, self).__init__(work_context)
        self.external_id = None
        self.odoo_record = None
        self.legacy = False

    def _get_odoo_data(self, legacy=False):
        """Return the raw Odoo data for ``self.external_id``"""
        if legacy:
            _model = self.work.model_name.lstrip("odoo.")
            odoo_data = self.work.legacy_odoo_api.read(
                _model, [self.external_id], {"fields": self._import_fields}
            )
            if len(odoo_data) != 1:
                raise IDMissingInBackend(
                    "No record found for ID %s:%s" % (_model, self.external_id)
                )
            data = odoo_data[0]
        else:
            data = self.backend_adapter.read(self.external_id)
        return data

    def _before_import(self):
        """Hook called before the import, when we have the Odoo
        data"""

    def _is_uptodate(self, binding, legacy=False):
        """Return True if the import should be skipped because
        it is already up-to-date in Odoo"""
        assert self.odoo_record
        if legacy:
            odoo_date = fields.Datetime.from_string(self.odoo_record["write_date"])
        else:
            odoo_date = self.odoo_record.write_date
            if not hasattr(self.odoo_record, "write_date") or not odoo_date:
                return  # no update date on Odoo, always import it.
        if not binding:
            return  # it does not exist so it should not be skipped
        sync = binding.sync_date
        if not sync:
            return
        from_string = fields.Datetime.from_string
        sync_date = from_string(sync)

        # if the last synchronization date is greater than the last
        # update in odoo, we skip the import.
        # Important: at the beginning of the exporters flows, we have to
        # check if the odoo_date is more recent than the sync_date
        # and if so, schedule a new import. If we don't do that, we'll
        # miss changes done in Odoo
        return odoo_date < sync_date

    def _import_dependency(
        self, external_id, binding_model, importer=None, force=False
    ):
        """Import a dependency.

        The importer class is a class or subclass of
        :class:`OdooImporter`. A specific class can be defined.

        :param external_id: id of the related binding to import
        :param binding_model: name of the binding model for the relation
        :type binding_model: str | unicode
        :param importer_component: component to use for import
                                   By default: 'importer'
        :type importer_component: Component
        :param force: if True, the record is updated even if it already
                       exists, note that it is still skipped if it has
                       not been modified on Odoo since the last
                       update. When False, it will import it only when
                       it does not yet exist.
        :type force: boolean
        """
        if not external_id:
            return
        binder = self.binder_for(binding_model)
        if force or not binder.to_internal(external_id):
            if importer is None:
                importer = self.component(
                    usage="record.importer", model_name=binding_model
                )
                # Todo: maybe we should use a context manager
                setattr(importer.work, "odoo_api", self.work.odoo_api)
                setattr(importer.work, "legacy_odoo_api", self.work.legacy_odoo_api)
            try:
                if binder.model._legacy_import:
                    importer.run_legacy(external_id, force=force)
                else:
                    importer.run(external_id, force=force)
            except NothingToDoJob:
                _logger.info(
                    "Dependency import of %s(%s) has been ignored.",
                    binding_model._name,
                    external_id,
                )

    def _import_dependencies(self, force=False):
        """Import the dependencies for the record

        Import of dependencies can be done manually or by calling
        :meth:`_import_dependency` for each dependency.
        """
        return

    def _map_data(self):
        """Returns an instance of
        :py:class:`~odoo.addons.connector.components.mapper.MapRecord`

        """
        return self.mapper.map_record(self.odoo_record)

    def _validate_data(self, data):
        """Check if the values to import are correct

        Pro-actively check before the ``_create`` or
        ``_update`` if some fields are missing or invalid.

        Raise `InvalidDataError`
        """
        return

    def _must_skip(self):
        """Hook called right after we read the data from the backend.

        If the method returns a message giving a reason for the
        skipping, the import will be interrupted and the message
        recorded in the job (if the import is called directly by the
        job, not by dependencies).

        If it returns None, the import will continue normally.

        :returns: None | str | unicode
        """
        return

    def _get_binding(self):
        return self.binder.to_internal(self.external_id)

    def _get_binding_with_data(self, binding):
        """This method is used to get the binding with cached odoo_record data.
        Need to inherit in model specific importer"""
        return binding

    # pylint: disable=W8121
    def _create_data(self, map_record, **kwargs):
        return map_record.values(for_create=True, legacy=self.legacy, **kwargs)

    def _create(self, data):
        """Create the Odoo record"""
        # special check on data before import
        self._validate_data(data)
        context = {**{"connector_no_export": True}, **self._get_context(data)}
        model = self.model.with_context(context)

        binding = model.create(data)
        _logger.info("%d created from Odoo %s", binding, self.external_id)
        return binding

    def _get_context(self, data):
        """Build the initial context for CRUD methods."""
        return {"lang": self.backend_record.default_lang_id.code}

    def _update_data(self, map_record, **kwargs):
        return map_record.values(legacy=self.legacy, **kwargs)

    def _update(self, binding, data):
        """Update an Odoo record"""
        # special check on data before import
        self._validate_data(data)
        context = {**{"connector_no_export": True}, **self._get_context(data)}
        binding.with_context(context).write(data)
        _logger.info("%d updated from Odoo %s", binding, self.external_id)
        return

    def _init_import(self, binding, external_id):
        """Hook called at before read data from backend"""
        return True

    def _after_import(self, binding, force=False):
        """Hook called at the end of the import

        Put here all processed that must be delayed with jobs
        """
        return True

    def _get_binding_odoo_id_changed(self, binding):
        # It is possible that OpenERP/Odoo deletes and creates records
        # instead of editing the information.
        #
        # e.g. In OpenERP it happens with ir.translation.
        #
        # This method will get the binding if needed
        return binding

    def run(self, external_id, force=False):
        """Run the synchronization

        :param external_id: identifier of the record on Odoo
        """
        lock_name = "import({}, {}, {}, {})".format(
            self.backend_record._name,
            self.backend_record.id,
            self.work.model_name,
            external_id,
        )
        _logger.info("Initializating {}".format(lock_name))
        self.external_id = external_id
        binding = self._get_binding()
        must_continue = self._init_import(binding, external_id)
        if not must_continue:
            _logger.info(
                "({}: {}) must no be imported!".format(
                    self.work.model_name, external_id
                )
            )
            return

        _logger.info("Reading data for {}".format(lock_name))

        try:
            self.odoo_record = self._get_odoo_data()
        except IDMissingInBackend:
            return _("Record does no longer exist in Odoo")

        binding = self._get_binding_with_data(binding)  # Todo experimental daha iyisini yaparsın
        if self._must_skip():
            _logger.info(
                "({}: {}) It must be skipped".format(self.work.model_name, external_id)
            )
            return

        if not force and self._is_uptodate(binding):
            _logger.info("Already up-to-date")
            return _("Already up-to-date.")

        # Keep a lock on this import until the transaction is committed
        # The lock is kept since we have detected that the informations
        # will be updated into Odoo
        self.advisory_lock_or_retry(lock_name)
        _logger.info("Resource {} locked".format(lock_name))
        if not binding:
            binding = self._get_binding_odoo_id_changed(binding)
        self._before_import()

        # import the missing linked resources
        _logger.info(
            "Importing dependencies ({}: {})".format(self.work.model_name, external_id)
        )
        self._import_dependencies(force=force)

        _logger.info("Mapping data ({}: {})".format(self.work.model_name, external_id))
        map_record = self._map_data()
        try:
            if binding:
                record = self._update_data(map_record)
                self._update(binding, record)
            else:
                record = self._create_data(map_record)
                binding = self._create(record)
        except Exception as e:
            _logger.error(
                "An error occurred while connecting the record {}: {}".format(
                    self.external_id, e
                )
            )
            raise

        _logger.info("Binding ({}: {})".format(self.work.model_name, external_id))
        self.binder.bind(self.external_id, binding)

        _logger.info(
            "Check if after import process must be executed ({}: {})".format(
                self.work.model_name, external_id
            )
        )
        self._after_import(binding, force)
        _logger.info("Finished ({}: {})!".format(self.work.model_name, external_id))

    def run_legacy(self, external_id, force=False):
        """Run the synchronization
        :param external_id: identifier of the record on Odoo
        :param data: dictionary with the data to import
        :param force: force the importation
        """
        self.legacy = True
        self.external_id = external_id

        data = self._get_odoo_data(legacy=True)

        lock_name = "import({}, {}, {}, {})".format(
            self.backend_record._name,
            self.backend_record.id,
            self.work.model_name,
            external_id,
        )
        _logger.info("Initializating {}".format(lock_name))
        binding = self._get_binding()
        self.odoo_record = data
        must_continue = self._init_import(binding, external_id)
        if not must_continue:
            _logger.info(
                "({}: {}) must no be imported!".format(
                    self.work.model_name, external_id
                )
            )
            return

        _logger.info("Reading data for {}".format(lock_name))

        if self._must_skip():
            _logger.info(
                "({}: {}) It must be skipped".format(self.work.model_name, external_id)
            )
            return

        if not force and self._is_uptodate(binding, legacy=True):
            _logger.info("Already up-to-date")
            return _("Already up-to-date.")

        # Keep a lock on this import until the transaction is committed
        # The lock is kept since we have detected that the informations
        # will be updated into Odoo
        self.advisory_lock_or_retry(lock_name)
        _logger.info("Resource {} locked".format(lock_name))
        if not binding:
            binding = self._get_binding_odoo_id_changed(binding)
        self._before_import()

        # import the missing linked resources
        _logger.info(
            "Importing dependencies ({}: {})".format(self.work.model_name, external_id)
        )
        self._import_dependencies(force=force)

        _logger.info("Mapping data ({}: {})".format(self.work.model_name, external_id))
        map_record = self._map_data()
        try:
            if binding:
                record = self._update_data(map_record)
                self._update(binding, record)
            else:
                record = self._create_data(map_record)
                binding = self._create(record)
        except Exception as e:
            _logger.error(
                "An error occurred while connecting the record {}: {}".format(
                    self.external_id, e
                )
            )
            raise

        _logger.info("Binding ({}: {})".format(self.work.model_name, external_id))
        self.binder.bind(self.external_id, binding)

        _logger.info(
            "Check if after import process must be executed ({}: {})".format(
                self.work.model_name, external_id
            )
        )
        self._after_import(binding, force)
        _logger.info("Finished ({}: {})!".format(self.work.model_name, external_id))


class BatchImporter(AbstractComponent):
    """The role of a BatchImporter is to search for a list of
    items to import, then it can either import them directly or delay
    the import of each item separately.
    """

    _name = "odoo.batch.importer"
    _inherit = ["base.importer", "base.odoo.connector"]
    _usage = "batch.importer"

    def run(self, filters=None, force=False):
        """Run the synchronization"""
        record_ids = self.backend_adapter.search(filters)
        for record_id in record_ids:
            self._import_record(record_id)

    def _import_record(self, external_id, force=False):
        """Import a record directly or delay the import of the record.

        Method to implement in sub-classes.
        """
        raise NotImplementedError


class DirectBatchImporter(AbstractComponent):
    """Import the records directly, without delaying the jobs."""

    _name = "odoo.direct.batch.importer"
    _inherit = "odoo.batch.importer"

    def _import_record(self, external_id, force=False):
        """Import the record directly"""
        self.model.import_record(self.backend_record, external_id, force=force)

    def _import_record_legacy(self, external_id, **kwargs):
        """Import the record directly with the legacy API.
        In this case, the data is already fetched by the adapter.
        """
        self.model.import_record_legacy(
            self.backend_record, external_id, **kwargs
        )


class DelayedBatchImporter(AbstractComponent):
    """Delay import of the records"""

    _name = "odoo.delayed.batch.importer"
    _inherit = "odoo.batch.importer"

    def _import_record(self, external_id, job_options=None, **kwargs):
        """Delay the import of the records"""
        delayable = self.model.with_delay(**job_options or {})
        delayable.import_record(self.backend_record, external_id, **kwargs)

    def _import_record_legacy(self, external_id, job_options=None, **kwargs):
        """Delay the import of the records with the legacy API.
        In this case, the data is already fetched by the adapter.
        """
        delayable = self.model.with_delay(**job_options or {})
        delayable.import_record_legacy(
            self.backend_record, external_id, **kwargs
        )
