# -*- coding: utf-8 -*-

from datetime import datetime, timedelta

from odoo import api, fields, tools, models, _
from odoo.exceptions import UserError, ValidationError

from odoo.addons.sync_common.models.common import WHITE_LIST_MODEL, SDREF_BUT_NO_TOUCH

import logging
import re

class DuplicateKey(KeyError):
    message_template = "Key \"%s\" already exist: \"%s\" -> \"%s\""
    message = ""
    key = None
    value = None

    def __init__(self, ddict, key, value):
        self.message = self.message_template % (key, ddict[key], value)
        self.key = key
        self.value = value

class RejectingDict(dict):
    def __setitem__(self, k, v):
        if k in list(self.keys()):
            raise DuplicateKey(self, k, v)
        else:
            return super(RejectingDict, self).__setitem__(k, v)

class IrModelData(models.Model):
    _inherit = 'ir.model.data'

    sync_date = fields.Datetime('Last Synchronization Date')
    version = fields.Integer('Version')
    last_modification = fields.Datetime('Last Modification Date')
    is_deleted = fields.Boolean(string='The record exists in database?', compute='_get_is_deleted')
    touched = fields.Text("Which records has been touched")
    force_recreation = fields.Boolean("Force record re-creation")
    resend = fields.Boolean('Received but pushed', help='Update received but must be pushed in the same sync: if true do not reset touch on update execution', index=True)


    def _get_is_deleted(self):
        datas = {}
        datas_by_id = {}
        for data in self:
            datas.setdefault(data['model'], set()).add(data['res_id'])
            data.is_deleted = False
            datas_by_id[data.id] = data

        for model, res_ids in list(datas.items()):
            obj = self.env.get(model)
            if obj is None:
                continue
            self.env.cr.execute("""
SELECT ARRAY_AGG(ir_model_data.id), COUNT(%(table)s.id) > 0
    FROM ir_model_data
    LEFT JOIN %(table)s ON %(table)s.id = ir_model_data.res_id
        WHERE ir_model_data.model = %%s AND ir_model_data.res_id IN %%s AND ir_model_data.id IN %%s
        GROUP BY ir_model_data.model, ir_model_data.res_id HAVING COUNT(%(table)s.id) = 0""" % {'table': obj._table}, [model, tuple(res_ids), tuple(self.ids)])  # not_a_user_entry
            for data_ids, exists in self.env.cr.fetchall():
                for _id in data_ids:
                    datas_by_id[_id] = not exists

    @api.model
    def update_sd_ref(self, sdref, vals, consider_resend=False):
        """Update a SD ref information. Raise ValueError if sdref doesn't exists."""
        domain = [('module','=','sd'),('name','=',sdref)]

        if consider_resend:
            domain.append(('resend', '=', False))

        record = self.search(domain)
        if not record.ids:
            if consider_resend:
                return True
            raise ValueError("Cannot find sdref %s!" % sdref)

        record.write(vals)
        return True

class Base(models.AbstractModel):
    _inherit = 'base'

    '''
    def get_model_ids(self, cr, uid, context=None):
        """
        Return a list of ir.model ids that match the current model (include inheritance)
        """
        def recur_get_model(model, res):
            ids = self.pool.get('ir.model').search(cr, uid, [('model','=',model._name)])
            res.extend(ids)
            for parent in list(model._inherits.keys()):
                recur_get_model(self.pool.get(parent), res)
            return res
        return recur_get_model(self, [])
    '''

    @api.model
    def _get_ids_to_push(self, rule):
        re_fieldname = re.compile(r"^\w+")
        domain = eval(rule.domain or '[]')
        export_fields = eval(rule.included_fields or '[]')
        if 'id' not in export_fields:
            export_fields.append('id')
        ids_need_to_push = self.need_to_push(
            [m.group(0) for m in map(re_fieldname.match, export_fields)],
            empty_ids=True
        )

        if not ids_need_to_push:
            return []
        domain.append(('id', 'in', ids_need_to_push))

        order = None
        if hasattr(self, '_sync_order'):
            # keep same id order at HQ and lower level
            order = self._sync_order

        return self.search(domain, order=order).ids

    def need_to_push(self, touched_fields=None, field='sync_date', empty_ids=False):
        """
        Check if records need to be pushed to the next synchronization process
        or not.

        One of those conditions needs to match:
            - sync_date < last_modification
            - sync_date is not set

        Plus, the result can be filtered to records that have changes in the
        fields given in touched_fields parameter.

        Note: sync_date field can be changed to other field using parameter
        sync_field

        Return type:
            - If a list of ids is given, it returns a list of filtered ids.
            - If an id is given, it returns the id itself or False it the
              record doesn't need to be pushed.

        :param cr: database cursor
        :param uid: current user id
        :param ids: id or list of the ids of the records to read
        :param touched_fields: reduce result to records that have fields
                               touched in touched_fields list.
        :param context: optional context arguments, like lang, time zone
        :type context: dictionary
        :return: list of ids that need to be pushed (or False for per record call)

        """
        if not empty_ids and not self.ids:
            return []

        sql_params = [self._name]
        add_sql = ''
        if not empty_ids:
            add_sql = ' res_id IN %s AND '
            sql_params.append(tuple(ids))

        if touched_fields is None:
            self.env.cr.execute("""\
SELECT res_id
    FROM ir_model_data
    WHERE module = 'sd' AND
          model = %s AND
          """+add_sql+"""
          ("""+field+""" < last_modification OR """+field+""" IS NULL)""",
                       sql_params) # not_a_user_entry
            result = [row[0] for row in self.cr.fetchall()]
        else:
            touched_fields = set(touched_fields)
            self.env.cr.execute("""\
SELECT res_id, touched
    FROM ir_model_data
    WHERE module = 'sd' AND
          model = %s AND
          COALESCE(touched, '') != '[]' AND
          """+add_sql+"""
          ("""+field+""" < last_modification OR """+field+""" IS NULL)""",
                       sql_params) # not_a_user_entry
            result = [row[0] for row in self.env.cr.fetchall()
                      if row[1] is None \
                      or touched_fields.intersection(eval(row[1]) if row[1] else [])]
        return result

    def touch(self, previous_values, synchronize, current_values=None,
              _previous_calls=None):
        """
        Touch the fields that has changed and/or mark the records to be
        synchronized. If previous_values is None, touch all the fields of every
        record. If synchronize is False, it doesn't mark the field has touched
        or mark the records for synchronize neither but call the 'on_change'
        method on the object if it exists.

        :param previous_values: dict or list of dict containing the result of a
                                read() call with ids given *before* the change
        :param synchronize: do we want to write the touched fields and update
                            last_modification date in ir.model.data
        :return:
        {
            id : {
                'field' : (previous_value, next_value),
                ...
            },
            ...
        }
        """

        assert not self._name == 'ir.model.data', \
            "Can not call this method on object ir.model.data!"
        assert synchronize or previous_values is not None, \
            "This call is useless"

        # UF-2272
        # enumeration of models where to skip their one2many(s)
        # was decided to do a specific skip versus global impact of touch...
        # list of o2m fields to skip, if empty ignore all o2m fields
        write_skip_o2m = {
            'supplier.catalogue': [],
            'account.bank.statement': ['line_ids'],
            'res.currency': ['rate_ids'],
            'product.list': [],
            'account.move.reconcile': ['line_id', 'line_partial_ids'],
            'replenishment.segment': ['line_ids', 'child_ids'],
            'replenishment.parent.segment': ['child_ids'],
            'shipment': ['picking_ids'],
            'account.analytic.account': ['dest_cc_link_ids'],
        }

        _previous_calls = _previous_calls or []
        me = (self._name, self.ids)
        if me not in _previous_calls:
            _previous_calls.append(me)
        else:
            return {}

        data = self.env.get('ir.model.data')
        if isinstance(synchronize, dict):
            data_base_values = synchronize
        elif synchronize:
            data_base_values = {
                'last_modification' : fields.Datetime.now(),
            }
        else:
            data_base_values = {}

        def touch(data_ids, touched_fields):
            # (US-1242) Trigger the sync. if the third party (journal, employee) has been modified in a register line
            if 'partner_type' in touched_fields and self._name == 'account.bank.statement.line':
                touched_fields.append('transfer_journal_id')
            if synchronize:
                data.browse(data_ids).write(dict(data_base_values, touched=str(sorted(touched_fields))))

        def filter_o2m(field_list):
            return [(f, self._fields[f])
                    for f in field_list
                    if self._fields[f].type == 'one2many']

        if previous_values is None:
            if current_values is not None:
                whole_fields = list(list(current_values.values())[0].keys())
            else:
                whole_fields = [x for x in self._fields if self._fields[x].type != 'properties']
            try:
                whole_fields.remove('id')
            except ValueError:
                pass

        # TODO
        # if not current_values:
        #    current_values = dict(
        #        (d['id'], d)
        #        for d in self.read(cr, uid, ids, whole_fields, context=context) )
        # touch things
        if previous_values is None:
            touch(
                self.get_sd_ref(field='id').values(),
                whole_fields+['id']
            )
            # handle one2many
            """
            TODO : no more needed
            o2m_fields = filter_o2m(whole_fields)

            # handle one2many (because orm don't call write() on them)
            for field, column in o2m_fields:
                for next_rec in list(current_values.values()):
                    if column.comodel_name == self._name:
                        continue
                    if self._name in write_skip_o2m and field in write_skip_o2m[self._name]:
                        continue

                    self.env.get(column.comodel_name).touch(
                        next_rec[field],
                        None,
                        data_base_values,
                        _previous_calls=_previous_calls
                    )
            """
        else:
            # convert previous_values to a mapping id -> dict_of_values
            # check that the previous_values provided is correct
            assert set(self.ids) == set(previous_values.keys()), \
                "Missing previous values: %s got, %s expected" \
                % (list(previous_values.keys()), self.ids)

            for res_id, (data_id, touched) in self.get_sd_ref(field=['id','touched']).items():
                modified_fields = set(previous_values[res_id])
                if modified_fields:
                    touch([data_id], list(
                        modified_fields.union(eval(touched) if touched else [])
                    ))
                # UF-2272 skip model's one2many(s)
                # handle one2many (because orm don't call write() on them)
                """
                TODO  no more needed ??
                whole_fields = previous_values[res_id]
                if synchronize:
                    for field, column in filter_o2m(whole_fields):
                        if self.env.context.get('from_orm_write', False) and \
                                self._name in write_skip_o2m and \
                                (not write_skip_o2m.get(self._name) or field in write_skip_o2m[self._name]):
                            # UF-2272 skip model's one2many(s)
                            continue
                        self.env.get(column.comodel_name).touch(
                            list(set(prev_rec[field] + next_rec[field])),
                            None,
                            data_base_values,
                            _previous_calls=_previous_calls,
                        )
                """

        return True

    @api.model_create_multi
    def create(self, vals_list):
        if self._name not in WHITE_LIST_MODEL + SDREF_BUT_NO_TOUCH or \
                self.env.context.get('sync_update_execution') or \
                self.env.context.get('sync_update_creation'):
            return super().create(vals_list)

        new_records = self.env[self._name]
        for vals in vals_list:
            new = super().create(vals)
            # TODO func fields to be added ?
            new.touch(previous_values=None, synchronize=True, current_values={new.id: vals})
            new_records += new

        return new_records

    def _write_sync_finalize(self):

        initial_values = self.env.cr.precommit.data.pop(f'sync.tracking.{self._name}', {})
        ids = [id_ for id_, vals in initial_values.items() if vals]
        if not ids:
            return


        touched_records = self.env[self._name]
        changed = {}
        for record in self.browse(ids).sudo():
            if not initial_values.get(record.id):
                continue

            for fname in initial_values[record.id].keys():
                if (field := record._fields[fname]).type == 'properties':
                    new_value = field.convert_to_read(record[fname], record)
                else:
                    new_value = record[fname]

                initial_value = initial_values.get(record.id, {}).get(fname)
                if new_value == initial_value or (not new_value and not initial_value):
                    continue

                changed.setdefault(record.id, []).append(fname)
                touched_records += record



        if changed:
            touched_records.touch(previous_values=changed, synchronize=True)

    def _compute_field_value(self, field):
        self._sync_track_prepare(f.name for f in self.pool.field_computed[field] if f.store)
        return super()._compute_field_value(field)

    def _sync_track_prepare(self, field_list):
        to_be_synchronized = (
            self._name in WHITE_LIST_MODEL and
            (not self.env.context.get('sync_update_execution') and
             not self.env.context.get('sync_update_creation')))

        if to_be_synchronized:
            self.env.cr.precommit.add(self._write_sync_finalize)
            initial_values = self.env.cr.precommit.data.setdefault(f'sync.tracking.{self._name}', {})
            for record in self:
                if not record.id:
                    continue
                values = initial_values.setdefault(record.id, {})
                if values is not None:
                    for fname in field_list:
                        value = (
                            # get the properties definition with the value
                            # (not just the dict with the value)
                            field.convert_to_read(record[fname], record)
                            if (field := record._fields[fname]).type == 'properties'
                            else record[fname]
                        )
                        values.setdefault(fname, value)

    def write(self, vals):
        self._sync_track_prepare(vals.keys())
        return super().write(vals)
# TODO
        #if self._name == 'replenishment.segment.line':
        #    self._set_period(cr, uid, ids, values, context=context)


    def get_sd_ref(self, field='name'):
        """
        Create or get the SD reference (replacement for link_with_ir_method).

        :param field: field to retrieve (normally 'name' by default)
        :param context: optional context arguments, like lang, time zone
        :type context: dictionary
        :return: dictionary with SD references

        """
        assert self._name != "ir.model.data", \
            "Cannot create xmlids on an ir.model.data object!"

        def get_fields(record):
            if isinstance(field, (list, tuple)):
                return tuple(getattr(record, f, False) for f in field)
            else:
                return getattr(record, field, False)

        if not self.ids:
            return {}

        if isinstance(field, (list, tuple)):
            fields_to_fetch = field[:]
        else:
            fields_to_fetch = [field]

        fields_to_fetch.append('res_id')

        model_data_obj = self.env.get('ir.model.data')
        sdref_ids = model_data_obj.search_fetch([('model', '=', self._name), ('res_id', 'in', self.ids), ('module', '=', 'sd')], fields_to_fetch)
        try:
            result = RejectingDict((data.res_id, get_fields(data)) for data in sdref_ids)
        except DuplicateKey as e:
            raise Exception("Duplicate definition of 'sd' xml_id: %d@ir.model.data" % e.key)

        missing_ids = self.env[self._name]
        seen = {}
        for record in self:
            if record.id not in result and record.id not in seen:
                missing_ids += record
                seen[record.id] = True

        if missing_ids:
            xmlids = dict(
                (data.res_id, "%(module)s_%(name)s" % data)
                for data in model_data_obj.search_fetch([
                                    ('model','=',self._name),('res_id','in', missing_ids.ids),
                                    '!',('module','in',['sd','__export__']),
                                    '!','&',('module','=','base'),('name','=like','main_%')
                                ], ['res_id', 'module', 'name']))
            now = fields.Datetime.now()
            identifier = self.env.get('sync.client.entity')._get_entity().identifier
            for res_id in missing_ids:
                name = xmlids.get(res_id.id, res_id.get_unique_xml_name(identifier))
                if self._name == 'account.journal':
                    # if sdref exists and is linked to another journal => deny
                    self.env.cr.execute("""
                        select
                            j.code
                        from
                            account_journal j, ir_model_data d
                        where
                            d.model = 'account.journal' and
                            d.module = 'sd' and
                            d.res_id = j.id and
                            d.name = %s and
                            j.id != %s
                    """, (name, res_id))
                    if self.env.cr.rowcount:
                        j_code = [x[0] for x in self.env.cr.fetchall()]
                        raise UserError(_('Journal sdref is already used by %s, please change the name or the code') % (', '.join(j_code), ))

                new_data_id = model_data_obj.create({
                    'noupdate' : False, # don't set to True otherwise import won't work
                    'module' : 'sd',
                    'last_modification' : now,
                    'model' : self._name,
                    'res_id' : res_id.id,
                    'version' : 1,
                    'name' : name,
                })
                result[res_id.id] = get_fields(new_data_id)
        return result

    def get_unique_xml_name(self, uuid, table_name=None):
        self.ensure_one()
        if table_name is None:
            table_name = self._name
        return uuid + '/' + table_name + '/' + str(self.id)

    def get_destination_name(self, dest_field, context=None):
        """
            @param ids : ids of the record from which we need to find the destination
            @param dest_field : field of the record from where the name will be extract
            @return a dictionnary with ids : dest_fields
        """

        result = dict.fromkeys(self.ids, False)
        if not dest_field:
            return result

        field = self._fields.get(dest_field)

        if field.type == 'many2one' and not field.comodel_name == 'msf.instance':
            for rec in self:
                if rec[dest_field]:
                    result[rec.id] = rec[dest_field][1]

        else:
            for rec in self:
                value = rec[dest_field]
                if value is False:
                    continue
                if field.type == 'many2one':
                    result[rec.id] = value.instance or False
                elif field.type in ('char','text'):
                    result[rec.id] = value
                else:
                    raise UseError(_("%(method)s doesn't implement field of type %(type)s, please contact system administrator to upgrade.") % {'method':'get_destination_name()', 'type':field['type']})

        assert set(ids) == set(result.keys()), "The return value of get_destination_name is not consistent"
        return result

    @api.model
    def clear_synchronization(self, ids):
        self._after_update_send(ids)
        self.env['ir.model.data'].search([
            ('module', '=', 'sd'),
            ('res_id', 'in', ids),
            ('model', '=', self._name)
        ]).write({'force_recreation':False, 'touched':False})
        return True

    @api.model
    def _after_update_send(self, ids):
        ''' Method called when a sync update is sent to the sync server '''
        pass

    @api.model
    def search_deleted(self, module=None, res_ids=None, for_sync=False):
        """
        Search for deleted entries in the table. It search for xmlids that are linked to not existing records. Beware that the domain applies to the ir.model.data
        """
        sql_add = ''
        sql_params = {'model': self._name}

        if module:
            sql_add = ' AND d.module=%(module)s '
            sql_params['module'] = module
        if for_sync:
            sql_add += ' AND (d.sync_date < d.last_modification OR d.sync_date IS NULL) '
        if res_ids:
            sql_add += ' AND d.res_id in %(res_ids)s '
            sql_params['res_ids'] = tuple(res_ids)

        self.env.cr.execute("""
        select d.res_id from ir_model_data d
        left join """+self._table+""" t on t.id = d.res_id and d.model=%(model)s
        where t.id is null and d.model=%(model)s"""+sql_add, sql_params)  # not_a_user_entry
        return [x[0] for x in self.env.cr.fetchall()]

    @api.model
    def find_sd_ref(self, sdrefs, field=None):
        """
        Find the ids of records based on their SD reference. If called on a
        model, search SD refs for this model only. Otherwise, search any
        record.
        """

        result_iterable = isinstance(sdrefs, (list, tuple))
        if not result_iterable:
            sdrefs = [sdrefs]

        sdrefs = tuple([_f for _f in sdrefs if _f])
        if not sdrefs:
            return {} if result_iterable else False

        if field is None:
            field = 'id' if self._name == 'ir.model.data' else 'res_id'

        real_field = field
        field = 'id' if field == 'is_deleted' else field

        if self._name == "ir.model.data":
            self.env.cr.execute("SELECT name, %s FROM ir_model_data WHERE module = 'sd' AND name IN %%s" % field, (sdrefs,))  # not_a_user_entry
        else:
            self.env.cr.execute("SELECT name, %s FROM ir_model_data WHERE module = 'sd' AND model = %%s AND name IN %%s" % field, (self._name, sdrefs))  # not_a_user_entry
        try:
            result = RejectingDict(self.env.cr.fetchall())
        except DuplicateKey as e:
            # Should never happen if called on other object than ir.model.data
            raise Exception("Duplicate definition of 'sd' xml_id: %d@ir.model.data" % e.key)

        if field != real_field:
            read_result = self.env.get('ir.model.data').browse(list(result.values())).read([real_field])
            read_result = dict((x['id'], x) for x in read_result)
            result = dict((sdref, read_result[id][real_field]) for sdref, id in list(result.items()))
        return result if result_iterable else result.get(sdrefs[0], False)

'''
    def version(self, cr, uid, ids, context=None):
        """
        Get the record version

        :param cr: database cursor
        :param uid: current user id
        :param ids: id or list of the ids of the records to read
        :param context: optional context arguments, like lang, time zone
        :type context: dictionary
        :return: dictionary with version per id

        """
        return self.get_sd_ref(cr, uid, ids, field='version', context=context)

    def synchronize(self, cr, uid, ids, context=None):
        """
        Update the SD ref (or create one if it does'n exists) and mark it to be
        synchronize and mark all fields as touched.

        Doesn't returns anything interesting
        """
        self.touch(cr, uid, ids, None, True, context=context)
        return True

    def sql_touch(self, cr, ids, fields):
        """
        Includes in the next synchro the records with the ids in param on the current object.

        Add new fields to the existing touched entries
        """
        if not ids:
            return True

        if isinstance(ids, int):
            ids = [ids]

        if isinstance(fields, str):
            fields = [fields]
        cr.execute("""
            select
                id, touched
            from ir_model_data
            where
                module='sd' and
                model=%s and
                res_id in %s and
                coalesce(touched, '') != '' and
                touched != '[]'
            for update
            """, (self._name, tuple(ids))
        )
        for x in cr.fetchall():
            f = list(set(fields).union(eval(x[1])))
            cr.execute("update ir_model_data set last_modification=NOW(), touched=%s where id = %s", ('%s'%sorted(f), x[0]))

        cr.execute("""
              UPDATE ir_model_data
              SET touched =%s, last_modification=NOW()
              WHERE module='sd'
              AND model=%s
              AND res_id IN %s
              AND
              (touched = '[]' or coalesce(touched, '') = '')
           """ , ('%s'%sorted(fields), self._name, tuple(ids))
        )
        return True

    def sql_synchronize(self, cr, ids, field='name'):
        """
        Includes in the next synchro the records with the ids in param on the current object.

        This is done via a "touch" in SQL in order to synch only the selected objects and not their related o2m.
        A specific "field" to synchronize can be given ("name" by default).
        """
        if ids:
            if isinstance(ids, int):
                ids = [ids]
            trigger_sync_sql = """
                                  UPDATE ir_model_data
                                  SET touched ='[''%s'']', last_modification=NOW()
                                  WHERE module='sd'
                                  AND model='%s'
                                  AND res_id IN %%s
                               """ % (field, self._name) # not_a_user_entry
            cr.execute(trigger_sync_sql, (tuple(ids),))
        return True



    def check_audit(self, cr, uid, method):
        audit_obj = self.pool.get('audittrail.rule')
        if audit_obj:
            return self.pool.get('audittrail.rule').to_trace(cr, 1, self._name, method)
        return False


    # BECAREFUL: This method is ONLY for deleting account.analytic.line by sync. NOT GENERIC!
    def message_unlink_analytic_line(self, cr, uid, source, unlink_info, context=None):
        model_name = unlink_info.model
        xml_id =  unlink_info.xml_id
        if model_name != self._name:
            return "Model not consistant"

        res_id = self.find_sd_ref(cr, uid, xmlid_to_sdref(xml_id), context=context)
        if not res_id:
            return "Object %s %s does not exist in destination" % (model_name, xml_id)

        # UF-2343: check if there is any data update with correction date is later than this delete message, if yes, ignore this message
        # Check if the correction_date of this record is older than the one of delete message, then ignore this delete message
        analytic_line = self.pool.get('account.analytic.line').browse(cr, uid, res_id, context=context)
        if not analytic_line.exists():
            return "Object %s %s already deleted by an update" % (model_name, xml_id)

        correction_date_in_db = analytic_line.correction_date
        correction_date = unlink_info.correction_date

        # UF-2343: to handle this if both time exists
        if correction_date_in_db and correction_date:
            date_in_db = datetime.strptime(correction_date_in_db, '%Y-%m-%d %H:%M:%S')
            date_in_sync = datetime.strptime(correction_date, '%Y-%m-%d %H:%M:%S')

            # If there is an update happening after the delete, then ignore this delete message
            if date_in_db > date_in_sync:
                return "The delete message is ignored as the analytic line got updated after this delete message."

        # UF-1011 delete the associated distribution line
        if analytic_line.distrib_line_id:
            analytic_line.distrib_line_id.unlink(context=context)

        return self.unlink(cr, uid, [res_id], context=context)

    @orm_method_overload
    def unlink(self, original_unlink, cr, uid, ids, context=None):
        if not ids: return True
        context = context or {}
        audit_rule_ids = self.check_audit(cr, uid, 'unlink')
        if audit_rule_ids:
            self.pool.get('audittrail.rule').audit_log(cr, uid, audit_rule_ids, self, ids, 'unlink', context=context)
        if context.get('sync_message_execution'):
            return original_unlink(self, cr, uid, ids, context=context)

        if self._name == 'ir.model.data' \
           and context.get('avoid_sdref_deletion'):
            return original_unlink(self, cr, uid,
                                   [rec.id for rec
                                    in self.browse(cr, uid, (ids if isinstance(ids, list) else [ids]), context=context)
                                       if not rec.module == 'sd'],
                                   context=context)

        # In an update creation context, references are deleted normally
        # In an update execution context, references are kept, but no
        # synchronization is made.
        # Otherwise, references are kept and synchronization is triggered
        # ...see?
        if self._name in WHITE_LIST_MODEL \
           and not context.get('sync_update_creation'):
            context = dict(context, avoid_sdref_deletion=True)
            if not context.get('sync_update_execution'):
                self.touch(cr, uid, ids, None, True, context=context)
            if hasattr(self, 'on_delete'):
                self.on_delete(cr, uid, ids, context=context)

        # US_394: Check if object have an ir.translation
        if self._name != 'ir.translation':
            tr_obj = self.pool.get('ir.translation')
            for obj_id in isinstance(ids, int) and [ids] or ids:
                # Add commat for prevent delete other object
                tr_name = str(self._name) + ',%'
                args = [('name', 'like', tr_name), ('res_id', '=', obj_id)]
                tr_ids = tr_obj.search(cr, uid, args, order='NO_ORDER')
                tr_obj.unlink(cr, uid, tr_ids)
        return original_unlink(self, cr, uid, ids, context=context)

    def purge(self, cr, uid, ids, context=None):
        """
        Just like unlink but remove the xmlid references also

        :param cr: database cursor
        :param uid: current user id
        :param ids: id or list of the ids of the records to read
        :param context: optional context arguments, like lang, time zone
        :type context: dictionary
        :return: id or list of ids of records matching the criteria and are deleted
        :raise AccessError: * if user tries to bypass access rules for read on the requested object.

        """
        if not ids: return True
        if not isinstance(ids, (list, tuple)): ids = (ids,)
        elif not isinstance(ids, tuple): ids = tuple(ids)
        ids = [_f for _f in ids if _f]
        if not ids: return True
        already_deleted = self.search_deleted(cr, uid, res_ids=ids, context=context)
        to_delete = list(set(ids) - set(already_deleted))
        self.unlink(cr, uid, to_delete, context=context)
        cr.execute("""\
DELETE FROM ir_model_data WHERE model = %s AND res_id IN %s
""", [self._name, ids])
        return True

    def search_deleted(self, cr, user, module=None, res_ids=None, context=None, for_sync=False):
        """
        Search for deleted entries in the table. It search for xmlids that are linked to not existing records. Beware that the domain applies to the ir.model.data

        :param cr: database cursor
        :param user: current user id
        :param args: list of tuples specifying the search domain [('field_name', 'operator', value), ...]. Pass an empty list to match all records.
        :param context: optional context arguments, like lang, time zone
        :type context: dictionary
        :return: id or list of ids of records matching the criteria and are deleted
        :raise AccessError: * if user tries to bypass access rules for read on the requested object.

        """
        sql_add = ''
        sql_params = {'model': self._name}

        if module:
            sql_add = ' AND d.module=%(module)s '
            sql_params['module'] = module
        if for_sync:
            sql_add += ' AND (d.sync_date < d.last_modification OR d.sync_date IS NULL) '
        if res_ids:
            sql_add += ' AND d.res_id in %(res_ids)s '
            sql_params['res_ids'] = tuple(res_ids)

        cr.execute("""
        select d.res_id from ir_model_data d
        left join """+self._table+""" t on t.id = d.res_id and d.model=%(model)s
        where t.id is null and d.model=%(model)s"""+sql_add, sql_params)  # not_a_user_entry
        return [x[0] for x in cr.fetchall()]

    def search_ext(self, cr, user, args, offset=0, limit=None, order=None, context=None, count=False):
        """
        Make a search on the model with an extended domain (replacement to eval_poc_domain)

        :param cr: database cursor
        :param user: current user id
        :param args: list of tuples specifying the search domain [('field_name', 'operator', value), ...]. Pass an empty list to match all records.
        :param offset: optional number of results to skip in the returned values (default: 0)
        :param limit: optional max number of records to return (default: **None**)
        :param order: optional columns to sort by (default: self._order=id )
        :param context: optional context arguments, like lang, time zone
        :type context: dictionary
        :param count: optional (default: **False**), if **True**, returns only the number of records matching the criteria, not their ids
        :return: id or list of ids of records matching the criteria
        :rtype: integer or list of integers
        :raise AccessError: * if user tries to bypass access rules for read on the requested object.

        """
        if context is None:
            context = {}

        real_args = []
        real_args_append = real_args.append
        for item in args:
            if isinstance(item, (tuple, list)):
                if len(item) != 3:
                    raise Exception("Malformed extended domain: %s" % tools.ustr(args))
                if isinstance(item[2], (tuple, list)) \
                   and len(item[2]) == 3 \
                   and isinstance(item[2][0], str) \
                   and isinstance(item[2][1], str) \
                   and isinstance(item[2][2], (tuple, list)):
                    model = item[2][0]
                    sub_domain = item[2][2]
                    field = item[2][1]
                    sub_obj = self.pool.get(model)
                    ids_list = sub_obj.search_ext(cr, user, sub_domain, context=context)
                    if ids_list:
                        new_ids = []
                        new_ids_append = new_ids.append
                        for data in sub_obj.read(cr, user, ids_list, [field], context=context):
                            if isinstance(data[field], (tuple, list)) \
                               and len(data[field]) == 2 \
                               and isinstance(data[field][0], int) \
                               and isinstance(data[field][1], str):
                                new_ids_append(data[field][0])
                            else:
                                new_ids_append(data[field])
                        ids_list = new_ids
                    real_args_append((item[0], item[1], ids_list))
                else:
                    real_args_append(item)
            else:
                real_args_append(item)

        context['rw_sync_in_progress'] = True
        return self.search(cr, user, real_args, offset=offset, limit=limit, order=order, context=context, count=count)

    def is_intersection(self, cr, uid, dest, context=None):
        if isinstance(dest, browse_record) and dest._name == 'res.partner':
            return dest.partner_type == 'section'
        return False

    def get_coordo_and_project_dest(self, cr, uid, ids, dest_field, context=None):
        res = dict.fromkeys(ids, False)
        for target_line in self.browse(cr, uid, ids, context=context, fields_to_fetch=[dest_field]):
            if hasattr(target_line, dest_field):
                instance = getattr(target_line, dest_field)
                if instance and instance.state == 'active':
                    res_data = [instance.instance]
                    if instance.level == 'coordo':
                        project_instances = []
                        for project in instance.child_ids:
                            if project.state == 'active':
                                project_instances.append(project.instance)
                        if project_instances:
                            res_data = project_instances
                    res[target_line.id] = res_data
        return res


    def get_message_arguments(self, cr, uid, res_id, rule=None, destination=False, context=None):
        """
            @param res_id: Id of the record from which we need to extract the args of the call
            @param rule: the message generating rule (browse record)
            @param destination: browse object of destination
            @return a list : each element of the list will be an arg after uid
                If the call is create_po(self, cr, uid, arg1, arg2, context=None)
                the list should contains exactly 2 element

            The default method will extract object information from the rule and return a list with a single element
            the object information json serialized

        """
        rule_dest_field = rule.destination_name
        fields = eval(rule.arguments)
        if isinstance(res_id, int):
            res_id = [res_id]
        res =  self.export_data_json(cr, uid, res_id, fields, destination=destination, rule_dest_field=rule_dest_field, context=context)
        return res['datas']

    def export_data_json(self, cr, uid, ids, fields_to_export, destination=False, rule_dest_field=False, context=None):
        """
        Export fields for selected objects

        :param cr: database cursor
        :param uid: current user id
        :param ids: list of ids
        :param fields_to_export: list of fields
        :param destination: browse object of destination
        :param rule_dest_field: if destination if False field on object with destination
        :param context: context arguments, like lang, time zone
        :rtype: dictionary with a *datas* matrix

        This method is used when exporting data via client menu

        """
        def __export_row_json(self, cr, uid, row, fields, json_data, intersection=False, context=None):
            if context is None:
                context = {}

            def get_name(row):
                name_relation = self.pool.get(row._table_name)._rec_name
                if isinstance(row[name_relation], browse_record):
                    row = row[name_relation]
                row_name = self.pool.get(row._table_name).name_get(cr, uid, [row.id], context=context)
                return row_name and row_name[0] and row_name[0][1] or ''

            def export_list(field, record_list, json_list):
                if not json_list: #if the list was not created before
                    json_list = [{} for i in record_list]

                for i in range(0, len(record_list)):
                    if len(field) > 1:
                        if not record_list[i]:
                            json_list[i] = {}
                        json_list[i] = export_field(field[1:], record_list[i], json_list[i])
                    else:
                        json_list[i] = get_name(record_list[i])

                return json_list

            def export_relation(field, record, json):
                if len(field) > 1:
                    if not json: #if the list was not create before
                        json = {}
                    return export_field(field[1:], record, json)
                else:
                    return get_name(record)

            def export_field(field, row, json_data):
                """
                    @param field: a list
                        size = 1 ['cost_price']
                        size > 1 ['partner_id', 'id']
                    @param row: the browse record for which field[0] is a valid field
                    @param json_data: json seralisation of row

                """
                if field[0] == 'id':
                    if intersection and row._name == 'product.product':
                        json_data['msfid'] = row['msfid']
                        if row['is_kept_product']:
                            cr.execute('select msfid from product_product where kept_product_id = %s and msfid is not null and msfid != 0 order by unidata_merge_date desc', (row['id'], ))
                            json_data['merged_msfid'] = '; '.join([str(x[0]) for x in cr.fetchall()])
                    json_data[field[0]] = row.get_xml_id(cr, uid, [row.id]).get(row.id)
                elif field[0] == '.id':
                    json_data[field[0]] = row.id
                else:
                    r = row[field[0]]
                    if isinstance(r, (browse_record_list, list)):
                        json_data[field[0]] = export_list(field, r, json_data.get(field[0]))
                    elif isinstance(r, (browse_record)):
                        json_data[field[0]] = export_relation(field, r, json_data.get(field[0]))
                    elif not r:
                        json_data[field[0]] = False
                    else:
                        if len(field) > 1:
                            raise ValueError('%s is not a relational field cannot use / to go deeper' % field[0])
                        json_data[field[0]] = r

                return json_data

            json_data = {}
            for field in fields:
                export_field(field, row, json_data)

            return json_data

        def fsplit(x):
            if x=='.id': return [x]
            return x.replace(':id','/id').split('/')

        fields_to_export = list(map(fsplit, fields_to_export))
        datas = []
        for row in self.browse(cr, uid, ids, context):
            intersection = False
            if not destination and rule_dest_field and hasattr(row, rule_dest_field):
                destination = row[rule_dest_field]
            if destination:
                intersection = self.is_intersection(cr, uid, destination)
            # context is json_data ???
            datas.append(__export_row_json(self, cr, uid, row, fields_to_export, context, intersection=intersection))
        return {'datas': datas}

'''
