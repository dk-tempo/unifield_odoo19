# -*- coding: utf-8 -*-

from odoo import api, fields, tools, models, _, SUPERUSER_ID
from odoo.modules.registry import Registry

from odoo.exceptions import UserError, ValidationError
import re
import logging

class MonitorLogger(object):
    def __init__(self, dbname, defaults=None):
        if defaults is None:
            defaults = {}


        db_registry = Registry(dbname)
        self.cr = db_registry.cursor()
        self.env = api.Environment(self.cr, SUPERUSER_ID, {})
        self.monitor = self.env.get('sync.monitor')
        #self.cr._cnx.autocommit = True
        self.info = {
            'status' : 'in-progress',
            'data_pull' : 'null',
            'data_pull_receive' : 'null',
            'data_pull_execute' : 'null',

            'msg_pull' : 'null',
            'msg_pull_receive' : 'null',
            'msg_pull_execute' : 'null',

            'msg_push' : 'null',
            'msg_push_create' : 'null',
            'msg_push_send' : 'null',

            'data_push' : 'null',
            'data_push_create' : 'null',
            'data_push_send' : 'null',

            'nb_msg_pull': 0,
            'nb_msg_push': 0,
            'nb_data_pull': 0,
            'nb_data_push': 0,
            'nb_msg_not_run': 0,
            'nb_data_not_run': 0,

        }
        self.ok_before_last_dump = False
        self.info.update(defaults)
        self.final_status = 'ok'
        self.messages = []
        self.link_to = set()
        self.row_id = self.monitor.create(self.info)

    def write(self):
        if not hasattr(self.env, 'cr'):
            raise Exception("Cannot write into a closed sync.monitor logger!")
        self.info['error'] = "\n".join(map(str, self.messages)) or False
        self.row_id.write(self.info)
        self.env.cr.commit()

    def __format_message(self, message, step):
        return "%s: %s" % (self.monitor._fields[step].string, message) \
               if step is not None and not step == 'status' and step in self.monitor._fields \
               else message

    def append(self, message='', step=None):
        self.messages.append(self.__format_message(message, step))
        return len(self.messages) - 1

    def replace(self, index, message, step=None):
        self.messages[index] = self.__format_message(message, step)

    def pop(self, index):
        return self.messages.pop(index)

    def switch(self, step, status):
        if step not in self.info:
            return

        if status in ('failed', 'aborted'):
            self.final_status = status
        self.info[step] = status

        endfield = '%s_enddate' % step
        if endfield in self.monitor._fields:
            self.info[endfield] = fields.Datetime.now()
        if step == 'status' and status != 'in-progress':
            self.info['end'] = fields.Datetime.now()
            SyncMonitor.last_status = (status, self.info['end'], self.info['nb_data_not_run'], self.info['nb_msg_not_run'])

    def update_sale_purchase_logger(self):
        # TODO
        return
        """
        # UTP-1200: Moved to this method and call this right after the message pull is done, not need to wait until
        # the end of sync since it's not relevant to the push but also to avoid unnecessary error caused by the
        # "in progress" issue (fixed but better to avoid)
        for model, column, res_id in self.link_to:
            # if a message failed, a rollback is made so the log message doesn't exist anymore
            if self.monitor.pool.get(model).exists(self.cr, self.uid, res_id, self.context):
                self.monitor.pool.get(model).write(self.cr, self.uid, res_id, {
                    column : self.row_id,
                }, context=self.context)
        """

    def close(self):
        if hasattr(self.env, 'cr'):
            self.switch('status', self.final_status)
            self.write()
            #TODO self.env.cr.close(True)
            self.env.cr.close()
            del self.env.cr

    def link(self, model, column, res_id):
        self.link_to.add((model, column, res_id))

    def unlink(self, model, column, res_id):
        try:
            self.link_to.remove((model, column, res_id))
        except KeyError:
            pass

    def __del__(self):
        self.close()



class SyncMonitor(models.Model):
    _name = "sync.monitor"
    _description = 'sync.monitor'

    _order = 'sequence_number desc, start desc, id desc'

    def _get_default_sequence_number(self):
        return int(self.env.get('ir.sequence').next_by_code('sync.monitor'))

    def _get_default_instance_id(self):
        # TODO
        return False
        """
        instance = self.pool.get('res.users').get_browse_user_instance(cr, uid, context)
        return instance and instance.id
        """

    def _get_default_destination_instance_id(self):
        #TODO
        return False
        """
        instance = self.pool.get('res.users').get_browse_user_instance(cr, uid, context)
        if instance:
            if instance.parent_id:
                if instance.parent_id.parent_id:
                    return instance.parent_id.parent_id.id
                return instance.parent_id.id
        return False
        """

    sequence_number = fields.Integer(string="Seq", required=True, readonly=True, default=_get_default_sequence_number)
    start = fields.Datetime(string="Start Date", required=True, readonly=True, default=fields.Datetime.now)
    end = fields.Datetime(string="End Date", readonly=True)
    user_rights = fields.Selection(string="User Rights", selection=[('ok', 'Ok'), ('null', '/'), ('in-progress', 'In Progress...'), ('failed', 'Failed'), ('aborted', 'Aborted')], readonly=True)
    data_pull = fields.Selection(string="Data Pull", selection=[('ok', 'Ok'), ('null', '/'), ('in-progress', 'In Progress...'), ('failed', 'Failed'), ('aborted', 'Aborted')], readonly=True)
    data_pull_enddate = fields.Datetime(string="End of Data Pull")
    data_pull_receive = fields.Selection(string="D. Pull receive", selection=[('ok', 'Ok'), ('null', '/'), ('in-progress', 'In Progress...'), ('failed', 'Failed'), ('aborted', 'Aborted')], readonly=True)
    data_pull_receive_enddate = fields.Datetime(string="End of Data Pull Receive")
    data_pull_execute = fields.Selection(string="D. Pull execute", selection=[('ok', 'Ok'), ('null', '/'), ('in-progress', 'In Progress...'), ('failed', 'Failed'), ('aborted', 'Aborted')], readonly=True)
    data_pull_execute_enddate = fields.Datetime(string="End of Data Pull Exec")
    msg_pull = fields.Selection(string="Msg Pull", selection=[('ok', 'Ok'), ('null', '/'), ('in-progress', 'In Progress...'), ('failed', 'Failed'), ('aborted', 'Aborted')], readonly=True)
    msg_pull_enddate = fields.Datetime(string="End of Msg Pull")
    msg_pull_receive = fields.Selection(string="Msg Pull receive", selection=[('ok', 'Ok'), ('null', '/'), ('in-progress', 'In Progress...'), ('failed', 'Failed'), ('aborted', 'Aborted')], readonly=True)
    msg_pull_receive_enddate = fields.Datetime(string="End of Msg Pull Receive")
    msg_pull_execute = fields.Selection(string="Msg execute", selection=[('ok', 'Ok'), ('null', '/'), ('in-progress', 'In Progress...'), ('failed', 'Failed'), ('aborted', 'Aborted')], readonly=True)
    msg_pull_execute_enddate = fields.Datetime(string="End of Msg Pull Exec")
    data_push = fields.Selection(string="Data Push", selection=[('ok', 'Ok'), ('null', '/'), ('in-progress', 'In Progress...'), ('failed', 'Failed'), ('aborted', 'Aborted')], readonly=True)
    data_push_enddate = fields.Datetime(string="End of Data Push")
    data_push_create = fields.Selection(string="Data Push create", selection=[('ok', 'Ok'), ('null', '/'), ('in-progress', 'In Progress...'), ('failed', 'Failed'), ('aborted', 'Aborted')], readonly=True)
    data_push_create_enddate = fields.Datetime(string="End of Data Push Create")
    data_push_send = fields.Selection(string="Data Push send", selection=[('ok', 'Ok'), ('null', '/'), ('in-progress', 'In Progress...'), ('failed', 'Failed'), ('aborted', 'Aborted')], readonly=True)
    data_push_send_enddate = fields.Datetime(string="End of Data Push Send")
    msg_push = fields.Selection(string="Msg Push", selection=[('ok', 'Ok'), ('null', '/'), ('in-progress', 'In Progress...'), ('failed', 'Failed'), ('aborted', 'Aborted')], readonly=True)
    msg_push_enddate = fields.Datetime(string="End of Msg Push")
    msg_push_create = fields.Selection(string="Msg Push Create", selection=[('ok', 'Ok'), ('null', '/'), ('in-progress', 'In Progress...'), ('failed', 'Failed'), ('aborted', 'Aborted')], readonly=True)
    msg_push_create_enddate = fields.Datetime(string="End of Msg Push Create")
    msg_push_send = fields.Selection(string="Msg Push Send", selection=[('ok', 'Ok'), ('null', '/'), ('in-progress', 'In Progress...'), ('failed', 'Failed'), ('aborted', 'Aborted')], readonly=True)
    msg_push_send_enddate = fields.Datetime(string="End of Msg Push Send")
    status = fields.Selection(string="Status", selection=[('ok', 'Ok'), ('null', '/'), ('in-progress', 'In Progress...'), ('failed', 'Failed'), ('aborted', 'Aborted')], readonly=True)
    error = fields.Text(string="Messages", readonly=True)
    state = fields.Selection(string="Is Syncing", compute="_is_syncing", selection=[('syncing', 'Syncing'), ('not_syncing', 'Done'), ('aborting', 'Aborting')], readonly=True)
    # TODO
    #instance_id = fields.Many2one(string="Instance", comodel_name="msf.instance", ondelete="set null", index=True, default=_get_default_instance_id)
    my_instance = fields.Boolean(string="My Instance", compute="_get_my_instance", search="_search_my_instance", readonly=True)
    nb_msg_pull = fields.Integer(string="# pull msg")
    nb_msg_push = fields.Integer(string="# push msg")
    nb_data_pull = fields.Integer(string="# pull data")
    nb_data_push = fields.Integer(string="# push data")
    nb_msg_not_run = fields.Integer(string="# msg not run")
    nb_data_not_run = fields.Integer(string="# data not run")

    # TODO
    #destination_instance_id = fields.Many2one(string="HQ Instance", comodel_name="msf.instance", ondelete="set null", default=_get_default_destination_instance_id)


    status_dict = {
        'ok' : 'Ok',
        'null' : '/',
        'in-progress' : 'In Progress...',
        'failed' : 'Failed',
        'aborted' : 'Aborted',
    }

    last_status = {}

    def _post_model_setup__(self):
        super()._post_model_setup__()

        if self.env.cr.dbname in SyncMonitor.last_status:
            return

        if not tools.sql.table_exists(self.env.cr, self._table):
            return

        # check rows existence
        monitor = self.search_fetch([('status', '!=', False)], ['status', 'end', 'nb_data_not_run', 'nb_msg_not_run'], limit=1, order='sequence_number desc')
        if not monitor:
            return
        # get the status of the last row
        self.env.registry[self._name].last_status = (monitor.status, monitor.end, monitor.nb_data_not_run, monitor.nb_msg_not_run)


    def _get_my_instance(self):
        """
        # TODO
        instance = self.pool.get('res.users').get_browse_user_instance(cr, uid, context)
        if not instance:
            return dict.fromkeys(ids, False)
        ret = {}
        for msg in self.read(cr, uid, ids, ['instance_id']):
            ret[msg['id']] = msg['instance_id'] and msg['instance_id'][0] == instance.id

        return ret
        """
        for x in self:
            x.my_instance = False


    def _search_my_instance(self, *a, **b):
        # TODO
        return []
        """
        res = []
        instance = self.pool.get('res.users').get_browse_user_instance(cr, uid, context)
        if not instance:
            return []

        for arg in args:
            if arg[1] not in ('=', '!='):
                raise osv.except_osv(_('Error !'), _('Filter not implemented on %s') % name)
            cond = arg[2] in ('True', 't', '1', 1, True)
            if arg[1] == '!=':
                cond = not cond
            if cond:
                res += ['|',('instance_id', '=', instance.id),('instance_id', '=', False)]
            else:
                res.append(('instance_id', '!=', instance.id))

        return res
        """

    @api.model
    def get_logger(self, defaults=None):
        return MonitorLogger(self.env.cr.dbname, defaults=defaults)

    """
    TODO
    def name_get(self, cr, user, ids, context=None):
        return [
            (rec.id, "(%d) %s" % (rec.sequence_number, rec.start))
            for rec in self.browse(cr, user, ids, context=context) ]
    """

    """
    TODO
    """

    def interrupt(self):
        return self.pool.get('sync.client.entity').interrupt_sync(cr, uid, context=context)

    def _is_syncing(self):
        is_syncing = self.env.get('sync.client.entity').is_syncing()
        max_id = 0
        max_id_state = False
        if is_syncing:
            max_monitor = self.search_fetch([('my_instance', '=', True)], ['status'], order='id desc', limit=1)
            if max_monitor and max_monitor.status == 'in-progress':
                max_id = max_monitor.id
            if max_id:
                if self.env.get('sync.client.entity').aborting:
                    max_id_state = "aborting"
                else:
                    max_id_state = "syncing"
        for rec in self:
            if rec.id == max_id:
                rec.state = max_id_state
            else:
                rec.state = 'not_syncing'

