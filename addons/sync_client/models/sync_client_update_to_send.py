# -*- coding: utf-8 -*-


from odoo import api, fields, tools, models, _
from odoo.exceptions import UserError, ValidationError
import logging
import re
from datetime import datetime


class SyncClientUpdateToSend(models.Model):

    _name = 'sync.client.update_to_send'
    _description = 'sync.client.update_to_send'
    _order = 'create_date desc, id desc'

    values = fields.Text(string="Values", readonly=True)
    model = fields.Char(string="Model", size=64, readonly=True, index=True)
    owner = fields.Char(string="Owner", size=128, readonly=True)
    sent = fields.Boolean(string="Sent?", readonly=True, index=True, default=False)
    create_date = fields.Datetime(string="Start date", readonly=True)
    sent_date = fields.Datetime(string="Sent date", readonly=True)
    session_id = fields.Char(string="Session Id", size=128, readonly=True, index=True)
    version = fields.Integer(string="Version", readonly=True)
    fancy_version = fields.Char(string="Version", compute="fancy_integer", readonly=True)
    rule_id = fields.Many2one(string="Generating Rule", comodel_name="sync.client.rule", ondelete="set null", readonly=True)
    sdref = fields.Char(string="SD ref", size=128, required=True, readonly=True, index=True)
    fieldsvalues = fields.Char(readonly=True, compute="fmt")
    is_deleted = fields.Boolean(string="Is deleted?", readonly=True, index=True, default=False)
    force_recreation = fields.Boolean(string="Force record recreation", readonly=True)
    handle_priority = fields.Boolean(string="Handle Priority")
    fields = fields.Text(string="Fields", readonly=True)


    _logger = logging.getLogger('sync.client')


    @api.model
    def create_update(self, rule, session_id):

        update = self
        def create_normal_update(self, rule):
            ids_to_compute = self._get_ids_to_push(rule)
            if not ids_to_compute:
                return 0

            export_fields = eval(rule.included_fields or '[]')
            if 'id' not in export_fields:
                export_fields.append('id')
            owners = self.browse(ids_to_compute).get_destination_name(rule.owner_field)

            if rule.direction == 'mission-private' and owners:
                for _id in owners:
                    own = owners[_id]
                    if not isinstance(own, (list, tuple)):
                        own = [own]
                    if self.env.get('msf.instance').search_count([('instance', 'in', own), ('level', '!=', 'coordo')]):
                        assert False, "mission-private rule, object: %s, id: %s, owner must be a coordo: %s" % (self._name, _id, own)

            min_offset = 0
            max_offset = len(ids_to_compute)

            while min_offset < max_offset:
                offset = min_offset + 200 < max_offset and min_offset +200 or max_offset
                records = self.env[self._name].browse(ids_to_compute[min_offset:offset])

                datas = records.export_data(export_fields)['datas']
                sdrefs = records.get_sd_ref(field=['name','version','force_recreation','id'])
                ustr_export_fields = str(export_fields)
                for (id, row) in zip(ids_to_compute[min_offset:offset], datas):
                    sdref, version, force_recreation, data_id = sdrefs[id]
                    for owner in (owners[id] if isinstance(owners[id], list) else [owners[id]]):
                        update_id = update.create({
                            'session_id' : session_id,
                            'rule_id' : rule.id,
                            'owner' : owner,
                            'model' : self._name,
                            'sdref' : sdref,
                            'version' : version + 1,
                            'force_recreation' : force_recreation,
                            'fields' : ustr_export_fields,
                            'values' : str(row),
                            'handle_priority' : rule.handle_priority,
                        })
                        update._logger.debug("Created 'normal' update model=%s id=%d (rule sequence=%d)" % (self._name, update_id.id, rule.id))
                min_offset += 200

            self.clear_synchronization(ids_to_compute)

            return len(ids_to_compute)

        def create_delete_update(self, rule):
            if not rule.can_delete:
                return 0

            ids_to_delete = self.search_deleted(module='sd', for_sync=True)
            if not ids_to_delete:
                return 0

            for rec, name in self.browse(ids_to_delete).get_sd_ref():
                update_id = update.create({
                    'session_id' : session_id,
                    'model' : self._name,
                    'rule_id' : rule.id,
                    'sdref' : name,
                    'is_deleted' : True,
                }, context=context)
                update._logger.debug("Created 'delete' update: model=%s id=%d (rule sequence=%d)" % (self._name, update_id.id, rule.id))

            self.clear_synchronization(ids_to_delete)

            return len(ids_to_delete)

        self = self.with_context(sync_update_creation=True)
        obj = self.env.get(rule.model)
        assert obj is not None; "Cannot find model %s of rule id=%d!" % (rule.model, rule.id)
        return (
            create_normal_update(obj, rule),
            create_delete_update(obj, rule)
        )

    @api.model
    def create_package(self, session_id=None, packet_size=None):
        domain = session_id and [('session_id', '=', session_id), ('sent', '=', False)] or [('sent', '=', False)]
        updates = self.search(domain, limit=packet_size,  order='id asc')

        if not updates:
            return False

        update_master = self.browse(updates[0].id)
        data = {
            'session_id' : update_master.session_id,
            'model' : update_master.model,
            'rule_id' : update_master.rule_id.server_id,
            'fields' : update_master.fields,
        }
        ids_in_package = []
        values = []
        deleted = []
        for update in updates:
            #only update from the same rules in the same package
            if update.rule_id.server_id != data['rule_id']:
                break
            if update.is_deleted:
                deleted.append(update.sdref)
            else:
                values.append({
                    'version' : update.version,
                    'values' : update.values,
                    'owner' : update.owner,
                    'sdref' : update.sdref,
                    'force_recreation' : update.force_recreation,
                    'handle_priority' : update.handle_priority,
                })
            ids_in_package.append(update.id)
        data['load'] = values
        data['unload'] = deleted
        self._logger.debug("package created for update ids=%s" % ids_in_package)
        return (ids_in_package, data)

    @api.model
    def sync_finished(self, session_id, sync_field='sync_date'):
        # specific case to split the active field on product.product
        # i.e: at COO an update received on product must not block a possible update on active field to the project
        self.env.cr.execute("""
            update product_product set active_sync_change_date = upd.create_date
                from sync_client_update_to_send upd, ir_model_data d, sync_client_rule rule
            where
                rule.id = upd.rule_id and
                rule.sequence_number in (602, 603) and
                d.model = 'product.product' and
                d.name = upd.sdref and
                product_product.id = d.res_id and
                upd.session_id = %s
        """, (session_id, ))


        self.env.cr.execute("""update ir_model_data d set
                version=upd.version, """+sync_field+"""=upd.create_date, resend='f'
            from sync_client_update_to_send upd
            where
                upd.session_id=%s and
                upd.sdref=d.name and
                d.module='sd'
        """, (session_id, )) # not_a_user_entry

        self.env.cr.execute("""update sync_client_update_to_send set sent='t', sent_date=%s where session_id=%s """, (fields.Datetime.now(), session_id))
        self._logger.debug(_("Push finished: %d updates") % self.env.cr.rowcount)

