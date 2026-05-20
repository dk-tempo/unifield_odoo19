# -*- coding: utf-8 -*-


from odoo import api, fields, tools, models, _
from odoo.exceptions import UserError, ValidationError
import logging
import re
from datetime import datetime
from odoo.addons.sync_common.models.common import normalize_xmlid, split_xml_ids_list

class SyncClientUpdateReceived(models.Model):

    _name = 'sync.client.update_received'
    _description = 'sync.client.update_received'
    _order = 'id desc'
    _rec_name = 'source'
    _sync_field = 'sync_field'

    line_error_re = re.compile(r"^Line\s+(\d+)\s*:\s*(.+)", re.S)
    _logger = logging.getLogger('sync.client')


    source = fields.Char(string="Source Instance", size=128, readonly=True)
    owner = fields.Char(string="Owner Instance", size=128, readonly=True)
    model = fields.Char(string="Model", size=64, readonly=True, index=True)
    sdref = fields.Char(string="SD ref", size=128, required=True, readonly=True, index=True)
    is_deleted = fields.Boolean(string="Is deleted?", readonly=True, index=True)
    force_recreation = fields.Boolean(string="Force record recreation", readonly=True)
    sequence_number = fields.Integer(string="Sequence", readonly=True)
    rule_sequence = fields.Integer(string="Rule Sequence", readonly=True, index=True)
    version = fields.Integer(string="Version", readonly=True)
    #fancy_version = fields.Char(string="Version", compute="fancy_integer", readonly=True)
    values = fields.Text(string="Values")
    fieldsvalues = fields.Char(readonly=True, compute="fmt")
    run = fields.Boolean(string="Run", readonly=True, index=True)
    log = fields.Text(string="Execution Messages", readonly=True)
    log_first_notrun = fields.Text(string="First not run message", readonly=True)
    fallback_values = fields.Text(string="Fallback values")
    handle_priority = fields.Boolean(string="Handle Priority", readonly=True)
    create_date = fields.Datetime(string="Synchro date/time", readonly=True)
    execution_date = fields.Datetime(string="Execution date", readonly=True)
    editable = fields.Boolean(string="Set editable")
    manually_ran = fields.Boolean(string="Has been manually tried", readonly=True)
    manually_set_run_date = fields.Datetime(string="Manually to run Date", readonly=True)
    fields = fields.Text(string="Fields")


    def _set_not_run(self, log):
        data = {
            'run': False,
            'editable': False,
            'execution_date': datetime.now()
        }
        if log:
            data['log'] = log
        self.write(data)

        # store 1st not run message
        if log and self.ids:
            self.env.cr.execute("""update sync_client_update_received set log_first_notrun=%s
                where id in %s and
                coalesce(log_first_notrun, '')=''
            """, (log, tuple(self.ids)))

        return True


    @api.model
    def unfold_package(self, packet):
        if not packet:
            return 0
        self._logger.debug("Unfold package %s" % packet['model'])
        if not self.env.get('ir.model').search([('model', '=', packet['model'])], limit=1):
            sync_log(self, "Model %s does not exist" % packet['model'], data=packet)
        packet_type = packet.get('type', 'import')
        if packet_type == 'import':
            data = {
                'source' : packet['source_name'],
                'model' : packet['model'],
                'fields' : packet['fields'],
                'sequence_number' : packet['sequence'],
                'fallback_values' : packet['fallback_values'],
                'rule_sequence' : packet['rule'],
            }
            for load_item in packet['load']:
                data.update({
                    'version' : load_item['version'],
                    'values' : load_item['values'],
                    'owner' : load_item['owner_name'],
                    'sdref' : load_item['sdref'],
                    'force_recreation' : load_item['force_recreation'],
                    'handle_priority' : load_item['handle_priority'],
                })
                self.create(data)
            return len(packet['load'])
        elif packet_type == 'delete':
            data = {
                'source' : packet['source_name'],
                'model' : packet['model'],
                'sequence_number' : packet['sequence'],
                'rule_sequence' : -packet['rule'],
                'is_deleted' : True,
            }
            for sdref in packet['unload']:
                self.create(dict(data, sdref=sdref))
            return len(packet['unload'])
        else:
            raise Exception("Unable to unfold unknown packet type: " % packet_type)

    def manual_set_as_run(self):
        self.write({'run': True, 'log': 'Set manually to run without execution', 'manually_set_run_date': fields.datetime.now(), 'editable': False})
        return True

    def ui_run(self):
        try:
            self.execute_update()
        except BaseException as e:
            sync_log(self, e)
        finally:
            self.write({'manually_ran': True})
        return True

    def execute_update(self):
        self = self.with_context({'lang': 'en_US', 'sync_update_execution': True})

        # force user to user_sync
        # TODO
        #uid = self.env.get('res.users')._get_sync_user_id(cr)

        local_entity = self.env.get('sync.client.entity').get_entity()

        # TODO
        # instance_level = _get_instance_level(self, cr, uid)

        # TODO
        #if ids is None:
        #    update_ids = self.search(cr, uid, [('run','=',False)], order='id asc', context=context)
        #else:
        #    update_ids = ids
        if not self.ids:
            return ''


        # Sort updates by rule_sequence
        update_groups = {}
        for update in self:
            if update.is_deleted:
                group_key = (update.sequence_number, 1, update.rule_sequence)
            else:
                group_key = (update.sequence_number, 0,  update.rule_sequence)
            update_groups.setdefault(group_key, []).append(update)

        def secure_import_data(obj, fields, values):
            try:
                self.env.cr.rollback_org, self.env.cr.rollback = self.env.cr.rollback, lambda:None
                self.env.cr.commit_org, self.env.cr.commit = self.env.cr.commit, lambda:None
                self.env.cr.execute("SAVEPOINT import_data")
                res = obj.with_context(module='sd', noupdate=True, mode='update').load(fields, values)
            except BaseException as e:
                self.env.cr.execute("ROLLBACK TO SAVEPOINT import_data")
                self._logger.exception("import failure")
                raise e
            else:
                if res.get('ids') and len(res['ids']) == len(values):
                    self.env.cr.execute("RELEASE SAVEPOINT import_data")
                else:
                    self.env.cr.execute("ROLLBACK TO SAVEPOINT import_data")
            finally:
                self.env.cr.rollback = self.env.cr.rollback_org
                self.env.cr.commit = self.env.cr.commit_org
            return res

        def secure_unlink_data(obj):
            try:
                self.env.cr.execute("SAVEPOINT unlink_update")
                # Keep a trace of the deletion
                if obj._name == 'account.move':
                    obj.unlink(check=False) #ITWG-84: Send this flag to not check on lines - otherwise it takes too much!
                else:
                    obj.unlink()
            except:
                self.env.cr.execute("ROLLBACK TO SAVEPOINT unlink_update")
                raise
            else:
                self.env.cr.execute("RELEASE SAVEPOINT unlink_update")

        def group_import_update_execution(obj, updates):
            import_fields = eval(updates[0].fields)
            fallback = eval(updates[0].fallback_values or '{}')
            message = ""
            values = []
            update_ids = []
            versions = []
            logs = {}

            def success(update_ids, versions):
                # write only for ids not in log as another write is performed
                # for those in logs. This avoid two writes on the same object
                ids_not_in_logs = list(set(update_ids) - set(logs.keys()))
                ids_in_logs = list(set(update_ids).intersection(list(logs.keys())))
                execution_date = datetime.now()
                if ids_not_in_logs:
                    self.browse(ids_not_in_logs).write({
                        'execution_date': execution_date,
                        'editable' : False,
                        'run' : True,
                        'log' : '',
                    })
                for update_id in ids_in_logs:
                    self.browse(update_id).write({
                        'execution_date': execution_date,
                        'editable' : False,
                        'run' : True,
                        'log' : logs[update_id],
                    })
                logs.clear()
                for sdref, version in list(versions.items()):
                    try:
                        self.env.get('ir.model.data').update_sd_ref(
                            sdref,
                            {
                                'version': version,
# TODO                                self._sync_field: fields.Datetime.now(),
                                'force_recreation' : False,
                                'touched' : '[]',
                            },
                            consider_resend=True,
                        )
                    except ValueError:
                        raise
                        self._logger.warning("Cannot find record %s during update execution process!" % update.sdref)

            #3 check for missing field : report missing fields
            bad_fields = self._check_fields(obj._name, import_fields)
            if bad_fields:
                message += "Missing or unauthorized fields found : %s\n" % ", ".join(bad_fields)
                bad_fields = [import_fields.index(x) for x in bad_fields]

            # Prepare updates
            # TODO: skip updates not preparable
            for update in updates:
                prev_nr_ids = self.search([('sdref', '=', update.sdref),
                                           ('is_deleted', '=', False),
                                              ('run', '=', False),
                                              ('rule_sequence', '=', update.rule_sequence),
                                              ('sequence_number', '<', update.sequence_number)])
                # previous not run on the same (sdref, rule_sequence): do not execute
                if prev_nr_ids:
                    if update.rule_sequence in (602, 603):
                        # update on product state, we don't care of previous NR
                        prev_nr_ids.write({'run': 't', 'log': 'Set as Run due to a later update on the same record/rule.', 'editable': False, 'execution_date': fields.Datetime.now()})
                    else:
                        update._set_not_run(log="Cannot execute due to previous not run on the same record/rule.")
                        continue

                row = eval(update.values)

                if update.model == 'product.merged':
                    old_product_sdref = row[import_fields.index('old_product_id/id')]
                    new_product_sdref = row[import_fields.index('new_product_id/id')]
                    if self.search_count([('sdref', 'in', [old_product_sdref, new_product_sdref]), ('run', '=', False), ('sequence_number', '<=', update.sequence_number)]):
                        update._set_not_run(log="Cannot execute due to previous not run on produts %s or %s" % (old_product_sdref, new_product_sdref))
                        continue

                #4 check for fallback value : report missing fallback_value
                #US-852: in case the account_move_line is given but not exist, then do not let the import of the current entry
                #US-2147: same thing for property_product_pricelist and property_product_pricelist_purchase

                # TODO
                instance_level = None
                result = self._check_and_replace_missing_id(import_fields, row, fallback, message, update, local_level=instance_level)

                if bad_fields :
                    row = [row[i] for i in range(len(import_fields)) if i not in bad_fields]

                if result['res']: #US-852: if everything is Ok, then do import as normal
                    if result.get('run_without_exec'):
                        self.write(cr, uid, update.id, {
                            'run': True,
                            'editable': False,
                            'execution_date': datetime.now(),
                            'log': 'Set as run without exec: %s' % (result['error_message'],),
                        })
                    elif obj._name == 'hr.employee' and obj._set_sync_update_as_run(cr, uid, dict(list(zip(import_fields, row))), update.sdref, context=context):
                        self.write(cr, uid, update.id, {
                            'run': True,
                            'editable': False,
                            'execution_date': datetime.now(),
                            'log': 'Set as Run because this employee already exists in the instance',
                        })
                    else:
                        values.append(row)
                        update_ids.append(update.id)
                        versions.append( (update.sdref, update.version) )

                        #1 conflict detection
                        if self._conflict(update.sdref, update.version):
                            #2 if conflict => manage conflict according rules : report conflict and how it's solve
                            index_id = eval(update.fields).index('id')
                            sd_ref = eval(update.values)[index_id]
                            logs[update.id] = "Warning: Conflict detected! in content: (%s, %r)" % (update.id, sd_ref)
                else: #US-852: if account_move_line is missing then ignore the import, and set it as not run
                    update._set_not_run(log=result['error_message'])

            if bad_fields:
                import_fields = [import_fields[i] for i in range(len(import_fields)) if i not in bad_fields]

            # Import batch of values
            while values:
                try:
                    res = secure_import_data(obj, import_fields, values)
                except Exception as import_error:
                    import_error = "Error during importation in model %s!\nUpdate ids: %s\nReason: %s\nData imported:\n%s\n" % (obj._name, update_ids, str(import_error), "\n".join([str(v) for v in values]))
                    # Rare Exception: import_data raised an Exception
                    self.browse(update_ids)._set_not_run(log=import_error.strip())
                    raise Exception(message+import_error)
                # end of the loop: all remaining values has been imported
                if res.get('ids') and len(res.get('ids')) == len(values):
                    success(update_ids, dict(versions))
                    break
                # import_data error detection
                #elif res[0] == -1:
                elif not res.get('ids'):
                    # Regular exception
                    import_message = res.get('messages')
                    line_error = self.line_error_re.search(import_message)
                    if line_error:
                        # Extract the failed data
                        value_index, import_message = int(line_error.group(1))-1, line_error.group(2)
                        data = dict(list(zip(import_fields, values[value_index])))
                        if "('warning', 'Warning !')" == import_message:
                            import_message = "Unknown! Please check the constraints of linked models. The use of raise Python's keyword in constraints typically give this message."
                        import_message = "Cannot import in model %s:\nData: %s\nReason: %s\n" % (obj._name, data, import_message)
                        message += import_message
                        # remove the row that failed
                        values.pop(value_index)
                        versions.pop(value_index)
                        self._set_not_run(cr, uid, [update_ids.pop(value_index)],
                                          log=import_message.strip(),
                                          context=context
                                          )
                    else:
                        # Rare case where no line is given by import_data
                        self.browse(update_ids).write({
                            'execution_date': datetime.now(),
                        })
                        message += "Cannot import data in model %s:\nReason: %s\n" % (obj._name, import_message)
                        raise Exception(message)
                    # Re-start import_data on rows that succeeds before
                    if value_index > 0:
                        # Try to import the beginning of the values and permit the import of the rest
                        # db rollback, previous updates will be replayed, clear the id cache
                        self.env.get('ir.model.data')._get_id.clear_cache(cr.dbname)
                        try:
                            res = secure_import_data(obj, import_fields, values[:value_index])
                            assert res[0] == value_index, res[2]
                        except Exception as import_error:
                            raise Exception(message+import_error.message)
                        success( update_ids[:value_index], \
                                 dict(versions[:value_index]) )
                        # truncate the rows just after the last non-failing row
                        values = values[value_index:]
                        update_ids = update_ids[value_index:]
                        versions = versions[value_index:]
                else:
                    # Rare exception, should never occur
                    raise AssertionError(message+"Wrong number of imported rows in model %s (expected %s, but %s imported)!\nUpdate ids: %s\n" % (obj._name, len(values), res[0], update_ids))

            if obj._name == 'ir.translation':
                self.env.get('ir.translation')._get_reset_cache_at_sync()
            elif obj._name == 'ir.model.access':
                self.env.get('ir.ui.menu')._clean_cache(cr.dbname)

            # Obvious
            assert len(values) == len(update_ids) == len(versions), \
                message+"""This error must never occur. Please contact the developper team of this module.\n"""

            return message

        def group_unlink_update_execution(obj, sdref_update_ids):
            obj_ids = obj.find_sd_ref(list(sdref_update_ids.keys()))
            done_ids = []
            for sdref, id in list(obj_ids.items()):
                try:
                    update_id = sdref_update_ids[sdref]
                    secure_unlink_data(obj, [id])
                except BaseException as e:
                    if isinstance(e, osv.except_osv):
                        error = '%s: %s' % (e.name, e.value)
                    else:
                        error = e
                    e = "Error during unlink on model %s!\nid: %s\nUpdate id: %s\nReason: %s\nSD ref:\n%s\n" \
                        % (obj._name, id, update_id, str(error), update.sdref)
                    self._set_not_run([update_id],
                                      log=str(e),
                                      context=context
                                      )

                    ########################################################################
                    #
                    # UFTP-116: Cannot raise the exception here, because it will stop the whole sync!!!! Just set this line to become not run, OR set it run but error message
                    # If we just set it not run, it will be again and again executed but never successfully, and thus it will remain for every not run, attempt to execute EVERYTIME!
                    # ???? So, just set it RUN?
                    ########################################################################

#                    raise
                else:
                    done_ids.append(update_id)

            d = self.browse(done_ids).write({
                'execution_date': fields.Datetime.now(),
                'editable' : False,
                'run' : True,
                'log' : '',
            })
            sdrefs = [elem['sdref'] for elem in d]
            for sdref in sdrefs:
                self.env.get('ir.model.data').update_sd_ref(
                    sdref, {
                        'sync_date': fields.Datetime.now(),
                        'touched' : '[]',
                        'resend': False,
                    })
            return

        error_message = ""
        imported, deleted = 0, 0
        rule_seq_list = list(update_groups.keys())
        rule_seq_list.sort()
        for rule_seq in rule_seq_list:
            updates = update_groups[rule_seq]
            obj = self.env.get(updates[0].model).with_context(sync_update_session=rule_seq[0])
            do_deletion = updates[0].is_deleted
            assert obj is not None, "Cannot find object model=%s" % updates[0].model
            # Remove updates about deleted records in the list
            duplicates = []
            sdref_update_ids = {}
            for update in updates:
                if do_deletion and update.sdref in sdref_update_ids:
                    duplicates.append(update.id)
                else:
                    sdref_update_ids[update.sdref] = update.id
            if duplicates:
                self.write(cr, uid, duplicates, {
                    'execution_date': datetime.now(),
                    'editable' : False,
                    'run' : True,
                    'log' : "This update has been ignored because it is duplicated.",
                }, context=context)
            # For bi-private rules, it is possible that the sdref doesn't exists /!\
            # - In case of import update, if sdref doesn't exists, the initial
            #   value is False in order to keep it for group execution
            # - For delete updates, if sdref doesn't exists, the initial value
            #   is True in order to keep ignore it from group deletion
            sdref_are_deleted = dict.fromkeys(list(sdref_update_ids.keys()), do_deletion)
            sdref_are_deleted.update(
                obj.find_sd_ref(list(sdref_update_ids.keys()), field='is_deleted'))
            update_id_are_deleted = {}
            for key in sdref_update_ids:
                update_id_are_deleted[sdref_update_ids[key]] = sdref_are_deleted[key]
            deleted_update_ids = [update_id for update_id, is_deleted in list(update_id_are_deleted.items()) if is_deleted]


            if deleted_update_ids:
                sdrefs = [elem['sdref'] for elem in self.browse(deleted_update_ids).read(['sdref'])]
                generic_domain = [
                    ('sdref', 'in', sdrefs),
                    ('run', '=', False),
                    ('is_deleted', '=', False)]
                to_set_run_domain = generic_domain + [('model', 'not in', OBJ_TO_RECREATE)]
                to_set_recreate_domain = generic_domain + [('model', 'in', OBJ_TO_RECREATE)]

                to_set_run_ids = self.search(to_set_run_domain)
                if to_set_run_ids:
                    to_set_run_ids.write({
                        'execution_date': fields.Datetime.now(),
                        'editable' : False,
                        'run' : True,
                        'log' : 'Manually set to run by the system. Due to a delete',
                    })

                # US-2837: check if some objects have to be recreated in case
                # an update is received after the object was deleted
                to_set_recreate_ids = self.search(to_set_recreate_domain)
                if to_set_recreate_ids:
                    deleted_update_ids = deleted_update_ids.filtered(lambda x: x not in to_set_recreate_ids)
                    deleted_update_ids.write({
                        'force_recreation': True
                    })

                update_ignored = deleted_update_ids - to_set_run_ids - to_set_recreate_ids
                if update_ignored:
                    update_ignored.write({
                        'execution_date': fields.Datetime.now(),
                        'editable' : False,
                        'run' : True,
                        'log' : "This update has been ignored because the record is marked as deleted or does not exists.",
                    })

            updates = [update for update in updates if update.id not in deleted_update_ids or
                       (not do_deletion and update.force_recreation)]

            if not updates:
                continue
            if do_deletion:
                group_unlink_update_execution(obj, dict((update.sdref, update.id) for update in updates if update.id not in duplicates))
                deleted += len(updates)
            else:
                error_message += group_import_update_execution(obj, updates)
                imported += len(updates)

        return (error_message.strip(), imported, deleted)

    @api.model
    def _check_fields(self, model, fields):
        """
            @return  : the list of unknown fields or unautorized field
        """
        bad_field = []
        fields_ref = self.env.get(model).fields_get()
        for field in fields:
            if field == "id":
                continue
            if '.id' in field:
                bad_field.append(field)
                continue

            part = field.split('/')
            if len(part) > 2 or (len(part) == 2 and part[1] != 'id') or not fields_ref.get(part[0]):
                bad_field.append(field)

        return bad_field

    @api.model
    def _remove_bad_fields_values(self, fields, values, bad_fields):
        for bad_field in bad_fields:
            i = fields.index(bad_field)
            fields.pop(i)
            values.pop(i)

        return (fields, values)

    @api.model
    def _conflict(self, sdref, next_version):
        data_obj = self.env.get('ir.model.data')
        data_ids = data_obj.find_sd_ref(sdref)
        # no data => no record => no conflict
        if not data_ids:
            return False
        data_rec = data_obj.browse(data_ids)
        return (not data_rec.is_deleted                                       # record doesn't exists => no conflict
                and (not data_rec.sync_date                                   # never synced => conflict
                     or (data_rec.last_modification                           # if last_modification exists, try the next
                         and data_rec.sync_date < data_rec.last_modification) # modification after synchro => conflict
                     or next_version < data_rec.version))                     # next version is lower than current version

    @api.model
    def _check_and_replace_missing_id(self, fields, values, fallback,
                                      message, update, local_level=None):
        ir_model_data_obj = self.env.get('ir.model.data')
        result = {
            'res': True,
            'error_message': ''
        }

        def check_xmlid(xmlid):
            module, sep, xmlid = xmlid.partition('.')
            assert sep, "Cannot find an xmlid without specifying its module: xmlid=%s" % module
            return not ir_model_data_obj.m_is_deleted(module, xmlid)

        for i, field, value in zip(list(range(len(fields))), fields, values):
            # replace English by MSF English for the updates on partners where English had been selected at some point
            # (so that the initial synchro on new instances isn't blocked)
            # TODO
            #if update.model == 'res.partner' and field == 'lang' and value == 'en_US':
            #    values[i] = 'en_MF'
            if '/id' not in field:
                continue
            if not value:
                continue
            res_val = []
            for xmlid in map(normalize_xmlid, split_xml_ids_list(value)):
                try:
                    if not check_xmlid(xmlid):
                        raise ValueError
                except ValueError:
                    try:
                        #US-852: if account_move_line is given, then cannot use the fallback value, but exit the import!
                        # THIS FIX COULD ALSO OPEN FOR OTHER BUG, BUT CHECK IF THE RULES THAT CONTAIN THE OBJECT (HERE account_move_line)
                        if 'account_move_line' in xmlid:
                            m, sep, sdref = xmlid.partition('.')
                            if self.search_count([('sdref', '=', sdref), ('run', '=', False)]):
                                result['res'] = False
                                result['error_message'] = 'Cannot execute due to missing the %s' % field
                                return result
                        if '/analytic_distribution/' in xmlid:
                            self.env.get('analytic.distribution').import_data(['name', 'id'], [['Auto created', xmlid]], mode='update', current_module='sd', noupdate=True)
                            res_val.append(xmlid)
                            continue

                        #US-2147: property_product_pricelist/id and
                        # property_product_pricelist_purchase/id are required
                        # fields, return False if the xmlid don't exists
                        # US-2478 return False if a Cost Center is synched without its parent
                        property_product_pricelist_missing = field in ('property_product_pricelist/id',
                                                                       'property_product_pricelist_purchase/id')
                        cc_parent_missing = 'account_analytic_account' in xmlid and 'category' in fields \
                                            and values[fields.index('category')] == 'OC' and field == 'parent_id/id'
                        if property_product_pricelist_missing or cc_parent_missing:
                            result['res'] = False
                            result['error_message'] = 'Cannot execute due to missing the %s' % field
                            return result

                        if update.model == 'res.partner.address' and field == 'partner_id/id':
                            # ignore update except if we have a previous NR on the partner
                            m, sep, sdref = xmlid.partition('.')
                            if self.search_count([
                                ('sdref', '=', sdref),
                                ('run', '=', False),
                                ('sequence_number', '<=', update.sequence_number)
                            ]):
                                return {'res': False, 'error_message': 'partner_id %s not found' % xmlid}
                            return {'res': True, 'run_without_exec': True, 'error_message': 'partner_id %s not found' % xmlid}
                        if update.model == 'account.tax' and field == 'partner_id/id':
                            return {'res': False, 'error_message': 'partner_id %s not found' % xmlid}
                        if update.model == 'account.analytic.line' and field in ('cost_center_id/id', 'destination_id/id'):
                            return {'res': False, 'error_message': 'Analytic Account %s not found' % xmlid}

                        if update.model == 'account.move.reconcile' and field in ['line_id/id', 'partial_line_ids/id']:
                            # not an issue if we are a project and no NR in the pipe
                            if local_level != 'project' or self.search_count([('sdref', '=', sdref), ('run', '=', False)]):
                                return {'res': False, 'error_message': 'JI %s not found' % xmlid}

                        fb = fallback.get(field, False)
                        if not fb:
                            raise ValueError("no fallback value defined")
                        elif check_xmlid(fb):
                            raise ValueError("fallback value %s has been deleted" \
                                             % fb)
                    except ValueError as e:
                        message += 'Missing record %s and %s, set to False\n' \
                                   % (xmlid, e)
                    else:
                        message += 'Missing record %s replaced by %s\n' \
                                   % (xmlid, fb)
                        res_val.append(fb)
                else:
                    res_val.append(xmlid)
            values[i] = ','.join(res_val) if res_val else False
        return result
