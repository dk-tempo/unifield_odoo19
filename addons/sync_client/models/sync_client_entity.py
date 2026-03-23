# -*- coding: utf-8 -*-

from psycopg2.extensions import ISOLATION_LEVEL_REPEATABLE_READ, TransactionRollbackError
from datetime import datetime, timedelta

from odoo import api, fields, tools, models, _
from odoo.exceptions import UserError, ValidationError
import uuid

from threading import Thread, RLock, Lock
import functools
import logging
import sys
import os
import hashlib

from odoo.addons.sync_common.models.common import get_md5, check_md5

MAX_EXECUTED_UPDATES = 500
MAX_EXECUTED_MESSAGES = 500


class SkipStep(Exception):
    pass


class AdminLoginException(Exception):
    def __init__(self):
        self.value = "Not connected to server. "\
            "You cannot use 'admin' in the config file for "\
            "automatic connection, please use a user dedicated "\
            "to the synchronization or manually connect before "\
            "launching a sync."

    def __str__(self):
        return repr(self.value)

"""
           if alias:
                        with self.pool.cursor() as new_cr:
                            self.with_env(self.env(cr=new_cr)).env['mail.alias'].browse(alias.id
                            )._alias_bounce_incoming_email(message, message_dict, set_invalid=True)

"""
"""
TODO
class BackgroundProcess(Thread):

    def __init__(self, cr, uid, method, context=None):
        super(BackgroundProcess, self).__init__()
        self.context = context
        self.uid = uid
        self.db, pool = pooler.get_db_and_pool(cr.dbname)
        connected = True
        try:
            chk_tz_msg = check_tz()
            if chk_tz_msg:
                raise ValidationError(chk_tz_msg)
            entity = pool.get('sync.client.entity')
            # Lookup method to call
            self.call_method = getattr(entity, method)
            # Check if we are not already syncing
            entity.is_syncing(raise_on_syncing=True)
            # Check if connection is up
            connection_obj = pool.get('sync.client.sync_server_connection')
            try:
                connection_obj.get_connection_from_config_file(cr, uid, context=context)
            except AdminLoginException as e:
                connected = False
                raise osv.except_osv(_("Error!"), _(e.value))
            if not pool.get('sync.client.sync_server_connection').is_connected:
                connected = False
                raise osv.except_osv(_("Error!"), _("Not connected: please try to log on in the Connection Manager"))
            # Check for update

            if hasattr(entity, 'upgrade'):
                up_to_date = entity.upgrade(cr, uid, context=context)
                if not up_to_date[0]:
                    # check if patchs should be applied automatically
                    connection = pool.get("sync.client.sync_server_connection")
                    sync_type = context and context.get('sync_type', 'manual')
                    automatic_patching = sync_type == 'automatic' and\
                        connection.is_automatic_patching_allowed(cr, uid)
                    if not automatic_patching:
                        cr.commit()
                        raise osv.except_osv(_('Error!'), _(up_to_date[1]))
        except BaseException as e:
            logger = pool.get('sync.monitor').get_logger(cr, uid, context=context)
            logger.switch('status', 'failed')
            if not connected:
                if context is None:
                    context = {}
                keyword = 'manual' in method and 'beforemanualsync' or 'beforeautomaticsync'
                context['logger'] = logger
                try:
                    pool.get('backup.config').exp_dump_for_state(cr, uid, keyword, context=context)
                except osv.except_osv as f:
                    logger.append(f.value)
                del context['logger']
            if isinstance(e, osv.except_osv):
                logger.append(e.value)
                raise
            else:
                error = "%s: %s" % (e.__class__.__name__, e)
                logger.append(error)
                raise osv.except_osv(_('Error!'), error)

    def run(self):
        cr = self.db.cursor()
        try:
            self.call_method(cr, self.uid, context=self.context)
            cr.commit()
        except:
            pass
        finally:
            cr.close(True)
"""

def sync_subprocess(step='status', defaults_logger={}):
    def decorator(fn):

        @functools.wraps(fn)
        def wrapper(self, cr, uid, *args, **kwargs):
            context = kwargs['context'] = kwargs.get('context') is not None and dict(kwargs.get('context', {})) or {}
            logger = context.get('logger')
            logger.switch(step, 'in-progress')
            logger.write()
            try:
                chk_tz_msg = check_tz()
                if chk_tz_msg:
                    raise BaseException(chk_tz_msg)
                patch_failed = check_patch_scripts(cr, uid, context=context)
                if patch_failed:
                    raise BaseException(patch_failed)

                res = fn(self, self.sync_cursor, uid, *args, **kwargs)
            except osv.except_osv:
                logger.switch(step, 'failed')
                raise
            except BaseException as e:
                # Handle aborting of synchronization
                if isinstance(e, OperationalError) and str(e) == 'Unable to use the cursor after having closed it':
                    logger.switch(step, 'aborted')
                    self.sync_cursor = None
                    raise
                logger.switch(step, 'failed')
                error = "%s: %s" % (e.__class__.__name__, getattr(e, 'message', e))
                self._logger.exception('Error in sync_process at step %s' % step)
                logger.append(error, step)
                raise
            else:
                logger.switch(step, 'ok')
                if isinstance(res, str) and res:
                    logger.append(res, step)
            finally:
                # gotcha!
                logger.write()
            return res
        return wrapper
    return decorator

def sync_process(step='status', need_connection=True, defaults_logger=None):
    is_step = not (step == 'status')

    def decorator(fn):

        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            """
            TODO
            chk_tz_msg = check_tz()
            if chk_tz_msg:
                raise osv.except_osv(_('Error'), chk_tz_msg)
            """
            # First, check if we can acquire the lock or return False
            sync_lock = self.sync_lock[self.env.cr.dbname]
            if not sync_lock.acquire(blocking=False):
                raise already_syncing_error

            # Lock is acquired, so don't put any code outside the try...catch!!
            res = False
            context = dict(self.env.context)
            try:
                # more information to the logger
                def add_information(logger):
                    entity = self.get_entity()
                    if entity.session_id:
                        logger.append(_("Update session: %s") % entity.session_id)

                # get the logger
                logger = context.get('logger')
                make_log = logger is None
                # we have to make the log
                """
                #TODO

                if make_log:
                    # get a whole new logger from sync.monitor object
                    context['logger'] = logger = \
                        self.env.get('sync.monitor').get_logger(defaults_logger)
                    context['log_sale_purchase'] = True

                    # create a specific cursor for the call
                    self.sync_cursor = pooler.get_db(cr.dbname).cursor()

                    if need_connection:
                        # Check if connection is up
                        connection_obj = self.env.get('sync.client.sync_server_connection')
                        if not connection_obj.is_connected:
                            if fn.__name__ == 'sync_manual_withbackup':
                                self.env.get('backup.config').exp_dump_for_state(cr, uid, 'beforemanualsync', context=context)
                            # try to coonect from the file
                            try:
                                if not connection_obj.get_connection_from_config_file(cr,
                                                                                      uid, context=context):
                                    raise osv.except_osv(_("Error!"), _("Not connected: please try to log on in the Connection Manager"))
                            except AdminLoginException as e:
                                raise osv.except_osv(_("Error!"), _(e.value))
                        # Check for update (if connection is up)
                        if hasattr(self, 'upgrade'):
                            # TODO: replace the return value of upgrade to a status and raise an error on required update
                            up_to_date = self.upgrade(cr, uid, context=context)
                            cr.commit()

                            # check if patchs should be applied automatically
                            connection_module = self.env.get("sync.client.sync_server_connection")
                            upgrade_module = self.env.get('sync_client.upgrade')

                            sync_type = context.get('sync_type', 'manual')
                            automatic_patching = sync_type == 'automatic' and\
                                connection_module.is_automatic_patching_allowed(cr, uid)
                            if not up_to_date[0] and not automatic_patching:
                                raise osv.except_osv(_("Error!"), _("Cannot check for updates: %s") % up_to_date[1])
                            elif 'last' not in up_to_date[1].lower():
                                logger.append( _("Update(s) available: %s") % _(up_to_date[1]) )
                                if automatic_patching:
                                    upgrade_module = self.env.get('sync_client.upgrade')
                                    upgrade_id = upgrade_module.create(cr, uid, {})
                                    upgrade_module.do_upgrade(cr, uid,
                                                              [upgrade_id], sync_type=context.get('sync_type', 'manual'))
                                    raise osv.except_osv(_('Sync aborted'),
                                                         _("Current synchronization has been aborted because there is update(s) to install. The sync will be restarted after update."))
                    else:
                        context['offline_synchronization'] = True
                    # more information
                    add_information(logger)
                patch_failed = check_patch_scripts(cr, uid, context=kwargs.get('context', {}))
                if patch_failed:
                    raise osv.except_osv(_('Error'), patch_failed)

                """
                # ah... we can now call the function!
                logger.switch(step, 'in-progress')
                logger.write()
                res = fn(self, self.sync_cursor, uid, *args, **kwargs)
                self.sync_cursor.commit()

                # is the synchronization finished?
                if need_connection and make_log:
                    entity = self.get_entity(cr, uid, context=context)
                    proxy = self.env.get("sync.client.sync_server_connection").get_connection(cr, uid, "sync.server.entity")
                    proxy.end_synchronization(entity.identifier, entity._hardware_id)
                    cr.execute('SHOW server_version')
                    result = cr.fetchone()
                    pg_version = result and result[0] or 'pgversion not found'
                    proxy.set_pg_ur_version(entity.identifier, entity._hardware_id, pg_version, entity.current_user_rights_name)
            except SkipStep:
                # res failed but without exception
                assert is_step, "Cannot have a SkipTest error outside a sync step process!"
                logger.switch(step, 'null')
                logger.append(_("ok, skipped."), step)
                if make_log:
                    raise ValidationError(_("You cannot perform this action now."))
            except BaseException as e:
                # Handle aborting of synchronization
                if isinstance(e, OperationalError) and str(e) == 'Unable to use the cursor after having closed it':
                    if make_log:
                        error = "Synchronization aborted"
                        logger.append(error, 'status')
                        self._logger.warning(error)
                        raise
                    else:
                        logger.switch(step, 'aborted')
                        self.sync_cursor = None
                        raise
                logger.switch(step, 'failed')
                error = "%s: %s" % (e.__class__.__name__, getattr(e, 'message', e))
                if is_step:
                    self._logger.exception('Error in sync_process at step %s' % step)
                    logger.append(error, step)
                if make_log:
                    self._logger.exception('Error in sync_process at step %s' % step)
                    add_information(logger)
                    raise
                raise
            else:
                logger.switch(step, 'ok')
                if isinstance(res, str) and res:
                    logger.append(res, step)
            finally:
                # gotcha!
                try:
                    if make_log:
                        all_status = list(logger.info.values())
                        if 'ok' in all_status and step == 'status' and logger.info.get(step) in ('failed', 'aborted') and not logger.ok_before_last_dump:
                            # ok_before_last_dump: if backup after sync fails do not generate a new backup
                            try:
                                self.env.get('backup.config').exp_dump_for_state(cr, uid, 'after%ssync' % context.get('sync_type', 'manual'), context=context)
                            except Exception as e:
                                logger.append("Cannot create backup")
                                self._logger.exception("Can't create backup %s" % tools.ustr(e))
                finally:
                    sync_lock.release()
                if make_log:
                    logger.close()
                    if self.sync_cursor is not None:
                        self.sync_cursor.close(True)
                else:
                    logger.write()
            return res
        wrapper._api_model = True
        return wrapper
    
    return decorator

already_syncing_error = lambda : ValidationError(_('OpenERP can only perform one synchronization at a time - you must wait for the current synchronization to finish before you can synchronize again.'))

def generate_new_hwid():
    '''
            @return: the new hardware id
    '''
    logger = logging.getLogger('sync.client')
    mac_list = []
    if sys.platform == 'win32':
        # generate a new hwid with uuid library
        hw_hash = uuid.uuid1().hex
    else:
        for line in os.popen("/sbin/ifconfig"):
            if line.find('Ether') > -1:
                mac_list.append(line.split()[4])
        if not mac_list:
            raise Exception('/sbin/ifconfig give no result, please check it is correctly installed')
        mac_list.sort()
        logger.info('Mac addresses used to compute hardware indentifier: %s' % ', '.join(x for x in mac_list))
        hw_hash = hashlib.md5((''.join(mac_list)).encode('utf8')).hexdigest()
    logger.info('Hardware identifier: %s' % hw_hash)
    return hw_hash

def get_hardware_id():
    logger = logging.getLogger('sync.client')
    if sys.platform == 'win32':
        # US-1746: on windows machine get the hardware id from the registry
        # to avoid hwid change with new network interface (wifi adtapters,
        # vpn, ...)

        import winreg
        sub_key = r'SYSTEM\ControlSet001\services\eventlog\Application\openerp-web-6.0'

        try:
            # check if there is hwid stored in the registry
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub_key,
                                0, winreg.KEY_READ) as registry_key:
                hw_hash, regtype = winreg.QueryValueEx(registry_key, "HardwareId")
                logger.info("HardwareId registry key found: %s" % hw_hash)
        except WindowsError:
            logger.info("HardwareId registry key not found, create it.")

            # generate a new hwid on windows
            hw_hash = generate_new_hwid()

            # write the new hwid in the registry
            try:
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, sub_key):
                    pass
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub_key,
                                    0, winreg.KEY_ALL_ACCESS) as registry_key:
                    winreg.SetValueEx(registry_key, "HardwareId", 0, winreg.REG_SZ, hw_hash)
            except WindowsError as e:
                logger.error('Error on write of HardwareId in the registry: %s' % e)
    else:
        hw_hash = generate_new_hwid()
    return hw_hash


class SyncClientEntity(models.Model):
    _name = 'sync.client.entity'
    _description = 'Synchronization Instance'
    _order = 'id'

    _logger = logging.getLogger('sync.client')

    renew_lock = {}
    aborting  = {}
    sync_lock = {}

    name = fields.Char(string="Instance Name", size=64, readonly=True, default=lambda self: self.env.cr.dbname)
    identifier = fields.Char(string="Identifier", size=64, readonly=True)
    oc = fields.Selection(string="Operational Center", selection=[('oca', 'OCA'), ('ocb', 'OCB'), ('ocba', 'OCBA'), ('ocg', 'OCG'), ('ocp', 'OCP'), ('waca', 'WACA'), ('ubuntu', 'UBUNTU')])
    parent = fields.Char(string="Parent Instance", size=64, readonly=True)
    update_last = fields.Integer(string="Last update", required=True, default=0)
    update_offset = fields.Integer(string="Update Offset", required=True, readonly=True, default=0)
    message_last = fields.Integer(string="Last message", required=True, default=0)
    email = fields.Char(string="Contact Email", size=512, readonly=True)
    state = fields.Char(string="State", compute="_get_state", readonly=True)
    session_id = fields.Char(string="Push Session Id", size=128)
    max_update = fields.Integer(string="Max Update Sequence", readonly=True)
    message_to_send = fields.Integer(string="Nb message to send", compute="_get_message_to_send", readonly=True)
    update_to_send = fields.Integer(string="Nb update to send", compute="_get_update_to_send", readonly=True)
    previous_hw = fields.Char(string="Last HW successfully used", size=128, index=True)
    usb_instance_type = fields.Selection(string="USB Instance Type", selection=(('', ''), ('central_platform', 'Central Platform'), ('remote_warehouse', 'Remote Warehouse')))
    user_rights_name = fields.Char(string="UR Version", size=256)
    user_rights_sum = fields.Char(string="UR Sum", size=256)
    user_rights_state = fields.Selection(string="UR State", selection=[('installed', 'Installed'), ('to_install', 'To install')])
    user_rights_data = fields.Binary(string="UR Zip file")
    current_user_rights_name = fields.Char(string="Installed UR Version", size=256, readonly=True)
    _hardware_id = fields.Char('Hardware ID', compute="_get_hardware_id")


    @api.constrains()
    def _entity_unique(self):
        if self.search_count([]) > 1:
            raise ValidationError( _('The Instance is unique, you cannot create a new one'))

    def __init__(self, name, bases, attrs):
        # TODO
        #print('INIT')
        super().__init__(name, bases, attrs)
        if self.env.cr.dbname not in SyncClientEntity.renew_lock:
            SyncClientEntity.renew_lock[self.env.cr.dbname] = Lock()
        self._renew_sync_lock()
        if self.env.cr.dbname not in SyncClientEntity.aborting:
            SyncClientEntity.aborting[self.env.cr.dbname] = False

    def _auto_init(self):
        super()._auto_init()
        if not self.search_count([]):
            self.create({'identifier' : self.generate_uuid()})

    def _get_hardware_id(self):
        self._hardware_id = get_hardware_id()

    @api.model
    def _renew_sync_lock(self):
        if not SyncClientEntity.renew_lock[self.env.cr.dbname].acquire(False):
            raise Exception("Can't acquire renew lock!")
        try:
            SyncClientEntity.sync_lock[self.env.cr.dbname] = RLock()
        finally:
            SyncClientEntity.renew_lock[self.env.cr.dbname].release()

    @api.model
    def generate_uuid(self):
        return str(uuid.uuid1())

    def _get_state(self):
        for entity in self:
            session_id = entity.session_id
            max_update = entity.max_update
            msg_send = int(entity.message_to_send)
            upt_send = int(entity.update_to_send)
            if not any([session_id, max_update, msg_send, upt_send]):
                entity.state = 'init'
            elif not any([session_id, max_update, upt_send]) and msg_send:
                entity.state = 'msg_push'
            elif not any([max_update, msg_send]) and upt_send and session_id:
                entity.state = 'update_send'
            elif not any([max_update, msg_send, upt_send]) and session_id:
                entity.state = 'update_validate'
            elif not any([session_id, msg_send, upt_send]) and max_update:
                entity.state = 'update_pull'
            else:
                entity.state = 'corrupted'

    def _get_message_to_send(self):
        """
        TODO
        nb = self.env.get('sync.client.message_to_send').search_count([('sent', '=', False), ('generate_message', '=', False)])
        self.message_to_send = nb
        """
        self.message_to_send = 0

    def _get_update_to_send(self):
        """
        TODO
        nb = self.env.get('sync.client.update_to_send').search_count([('sent', '=', False)])
        self.update_to_send = nb
        """
        self.update_to_send = 0

    @api.model
    def get_entity(self):
        return self.search([])[0]

    @api.model
    def _get_entity(self):
        """
        private method to get entity with uid = 1
        """
        return self.sudo().get_entity()

    @api.model
    def get_uuid(self):
        return self.get_entity().identifier



    @api.model
    def get_model_white_list(self):
        # todo
        '''
        return a set of all models involved in the synchronization process
        '''
        model_field_dict = {}

        # search for model of sync_server.sync_rule
        if self.env.get('sync_server.sync_rule'):
            rule_module = self.env.get('sync_server.sync_rule')
            model_field_name = 'model_id'
        else:
            rule_module = self.env.get('sync.client.rule')
            model_field_name = 'model'
        # TODO JFB RR: remove USB rules from sync / instances
        obj_ids = rule_module.search(cr, uid, [('active', '=', True), ('type', '!=', 'USB')])
        for obj in rule_module.read(cr, uid, obj_ids, [model_field_name, 'included_fields']):
            if obj[model_field_name] not in model_field_dict:
                model_field_dict[obj[model_field_name]] = set()
            model_field_dict[obj[model_field_name]].update(eval(obj['included_fields']))

        # search for model of sync_server.message_rule
        if self.env.get('sync_server.message_rule'):
            rule_module = self.env.get('sync_server.message_rule')
            model_field_name = 'model_id'
        else:
            rule_module = self.env.get('sync.client.message_rule')
            model_field_name = 'model'
        obj_ids = rule_module.search(cr, uid, [('active', '=', True)])
        for obj in rule_module.read(cr, uid, obj_ids, [model_field_name, 'arguments']):
            if obj[model_field_name] not in model_field_dict:
                model_field_dict[obj[model_field_name]] = set()
            model_field_dict[obj[model_field_name]].update(eval(obj['arguments']))

        model_set = set(model_field_dict.keys())

        def get_field_obj(model, field_name):
            model_obj = self.env.get(model)
            field_obj = None
            if field_name in model_obj._columns:
                field_obj = model_obj._columns[field_name]
            elif field_name in model_obj._inherit_fields:
                field_obj = model_obj._inherit_fields[field_name][2]
            return field_obj


        # for each field corresponding to each model, check if it is a m2m m2o or o2m
        # if yes, add the model of the relation to the model set

        for model, field_list in list(model_field_dict.items()):
            field_list_to_parse = [x for x in field_list if '/id' in x]
            if not field_list_to_parse:
                continue

            for field in field_list_to_parse:
                field = field.replace('/id', '')
                if len(field.split('/')) == 2:
                    related_field, field = field.split('/')
                    field_obj = get_field_obj(model, related_field)
                    related_model = field_obj._obj
                    field_obj = get_field_obj(related_model, field)
                else:
                    field_obj = get_field_obj(model, field)
                if field_obj and field_obj._type in ('many2one', 'many2many', 'one2many'):
                    model_set.add(field_obj._obj)

        # specific cases to sync BAR and FAR
        to_remove = ['ir.ui.view', 'ir.model.fields', 'ir.sequence']
        for f in to_remove:
            if f in model_set:
                model_set.remove(f)

        return model_set

    #@sync_process('data_push')
    @api.model
    def push_update(self):
        """
            Push Update
        """
        if self.env.context.get('lang') != 'en_US':
            self = self.with_context({'lang': 'en_US'})

        if not self.env.is_superuser():
            self = self.sudo()

        logger = self.env.context.get('logger')
        entity = self.get_entity()

        if entity.state not in ('init', 'update_send', 'update_validate'):
            raise SkipStep

        cont = False
        if cont or entity.state == 'init':
            updates_count = self.create_update()
            self.env.cr.commit()
            cont = updates_count > 0
            self._logger.info("Push data :: Updates created: %d" % updates_count)
        if cont or entity.state == 'update_send':
            updates_count = self.send_update()
            self.env.cr.commit()
            cont = True
            self._logger.info("Push data :: Updates sent: %d" % updates_count)
            if logger:
                logger.info['nb_data_push'] = updates_count
        if cont or entity.state == 'update_validate':
            server_sequence = self.validate_update()
            self.env.cr.commit()
            if server_sequence:
                self._logger.info(_("Push data :: New server's sequence number: %s") % server_sequence)
        return True

    #@sync_subprocess('data_push_create')
    @api.model
    def create_update(self):
        """
        TODO
        cr = pooler.get_db(oldcr.dbname).cursor()
        cr._cnx.set_isolation_level(ISOLATION_LEVEL_REPEATABLE_READ)
        """
        nb_tries = 1
        MAX_TRIES = 10
        while True:
            try:
                logger = self.env.context.get('logger')
                updates = self.env.get(self.env.context.get('update_to_send_model', 'sync.client.update_to_send'))

                def prepare_update(session):
                    updates_count = 0
                    for rule_id in self.env.get('sync.client.rule').search([('type', '!=', 'USB')]):
                        updates_count += sum(updates.create_update(rule_id, session))
                    return updates_count

                entity = self.get_entity()
                session = str(uuid.uuid1())
                updates_count = prepare_update(session)
                if updates_count > 0:
                    entity.write({'session_id' : session})
                self.env.cr.commit()
# TODO
# cr.close(True)
                return updates_count
            except TransactionRollbackError:
                self.env.cr.rollback()
                if nb_tries == MAX_TRIES:
                    msg = _("Unable to generate updates after %d tries") % MAX_TRIES
                    if logger:
                        logger.append(msg)
                        logger.write()
                    self._logger.info(msg)
                    # TODO
                    # cr.close(True)
                    raise
                msg = _("Unable to generate updates, retrying %d/%d") % (nb_tries, MAX_TRIES)
                if logger:
                    logger.append(msg)
                    logger.write()
                self._logger.info(msg)
                nb_tries += 1
            except:
                """
                TODO
                cr.rollback()
                cr.close(True)
                """
                raise


    #@sync_subprocess('data_push_send')
    @api.model
    def send_update(self):
        logger = self.env.context.get('logger')
        updates = self.env.get(self.env.context.get('update_to_send_model', 'sync.client.update_to_send'))

        max_packet_size = self.env.get("sync.client.sync_server_connection")._get_connection_manager().max_size
        proxy = self.env.get("sync.client.sync_server_connection").get_connection("sync.server.sync_manager")
        entity = self.get_entity()

        def create_package():
            return updates.create_package(entity.session_id, max_packet_size)

        def send_package(ids, packet):
            context={'md5': get_md5(packet)}
            res = proxy.receive_package(entity.identifier, entity._hardware_id, packet)
            if not res[0]:
                raise Exception(res[1])
            updates.browse(ids).write({'sent' : True})
            return (len(packet['load']), len(packet['unload']))

        # get update count
        max_updates = updates.search_count([('sent','=',False)])
        if max_updates == 0:
            return 0

        imported, deleted = 0, 0
        logger_index = None
        res = create_package()
        while res:
            imported_package, deleted_package = send_package(*res)
            imported += imported_package
            deleted += deleted_package
            if logger:
                if logger_index is None: logger_index = logger.append()
                logger.replace(logger_index, _("Update(s) sent: %d import update(s) + %d delete update(s) on %d update(s)") % (imported, deleted, max_updates))
                logger.write()
            res = create_package()

        if logger and (imported or deleted):
            logger.replace(logger_index, _("Update(s) sent: %d import update(s) and %d delete update(s) = %d total update(s)") \
                           % (imported, deleted, (imported + deleted)))

        #state update_send => update_validate
        return imported + deleted

    @api.model
    def validate_update(self):
        updates = self.env.get(self.env.context.get('update_to_send_model', 'sync.client.update_to_send'))

        entity = self.get_entity()
        session_id = entity.session_id
        proxy = self.env.get("sync.client.sync_server_connection").get_connection("sync.server.sync_manager")
        res = proxy.confirm_update(entity.identifier, entity._hardware_id, session_id, get_md5(session_id))
        if not res[0]:
            raise Exception(res[1])
        updates.sync_finished(session_id)
        entity.write({'session_id' : ''})
        #state update validate => init
        return res[1]

    @api.model
    def set_rules(self):
        entity = self.get_entity()
        proxy = self.env.get("sync.client.sync_server_connection").get_connection("sync.server.sync_manager")
        res = proxy.get_model_to_sync(entity.identifier, entity._hardware_id)
        if not res[0]:
            raise Exception(res[1])

        entity.write({'previous_hw': entity._hardware_id})
        check_md5(res[2], res[1], _('method set_rules'))
        self.env.get('sync.client.rule').save(res[1])
        logger = self.env.context.get('logger')
        if logger and self.env.get('sync.client.message_rule'):
            server_model_white_set = self.get_model_white_list()
            difference = server_model_white_set.difference(WHITE_LIST_MODEL)
            if difference:
                msg = 'Warning: Some models used in the synchronization '\
                    'rule are not present in the WHITE_LIST_MODEL: %s'
                logger.append(_(msg) % ' ,'.join(list(difference)))
        return True

    def install_user_rights(self, cr, uid, context=None):
        if not context:
            context = {}

        logger = context.get('logger')
        entity = self.get_entity(cr, uid, context)
        encoded_zip = entity.user_rights_data
        plain_zip = b64decode(encoded_zip)

        self.env.get('user_rights.tools').load_ur_zip(cr, uid, plain_zip, sync_server=False, logger=logger, context=context)
        return True

    @sync_process('user_rights')
    def check_user_rights(self, cr, uid, context=None):
        if not bool(self.env.get('res.users').get_browse_user_instance(cr, uid)):
            # init sync, groups with former xmlid must first be pulled
            return False

        if context is None:
            context = {}
        context['lang'] = 'en_US'
        logger = context.get('logger')

        entity = self.get_entity(cr, uid, context)
        proxy = self.env.get("sync.client.sync_server_connection").get_connection(cr, uid, "sync.server.sync_manager")
        res = proxy.get_last_user_rights_info(entity.identifier, entity._hardware_id)
        if not res.get('sum'):
            return True

        to_install = False
        if res.get('sum') != entity.user_rights_sum:
            if logger:
                logger.append(_("Download new User Rights: %s") % res.get('name'))
                logger.write()
            ur_data_encoded = proxy.get_last_user_rights_file(entity.identifier, entity._hardware_id, res.get('sum'))
            ur_data = b64decode(ur_data_encoded)
            computed_hash = hashlib.md5(ur_data).hexdigest()
            if computed_hash != res.get('sum'):
                raise Exception('User Rights: computed sum (%s) and server sum (%s) differ' % (computed_hash, res.get('sum')))
            entity.write({'user_rights_name': res.get('name'), 'user_rights_sum': computed_hash, 'user_rights_state': 'to_install', 'user_rights_data': ur_data_encoded})
            to_install = True


        if to_install or entity.user_rights_state == 'to_install':
            try:
                cr.execute("SAVEPOINT import_userrights")
                self.install_user_rights(cr, uid, context=context)
                entity.write({'user_rights_state': 'installed', 'user_rights_data': False, 'current_user_rights_name': res.get('name')})
            except Exception as e:
                cr.execute("ROLLBACK TO SAVEPOINT import_userrights")
                if logger:
                    logger.append("Import UR error: %s" % e)
                    logger.write()
                self._logger.error('Import UR error: %s' % tools.misc.get_traceback(e))
            else:
                cr.execute("RELEASE SAVEPOINT import_userrights")
                cr.commit()

        self.env.get('ir.ui.menu')._clean_cache(cr.dbname)
        self.env.get('ir.model.access').call_cache_clearing_methods(cr)
        return True

    @sync_process('get_surveys')
    def get_surveys(self, cr, uid, context=None):
        try:
            cr.execute("SAVEPOINT import_surveys")
            survey_obj = self.env.get('sync_client.survey')
            logger = context.get('logger')

            entity = self.get_entity(cr, uid, context)
            proxy = self.env.get("sync.client.sync_server_connection").get_connection(cr, uid, "sync.server.sync_manager")
            last_date = survey_obj.get_last_write(cr, uid)
            res = proxy.get_surveys(entity.identifier, entity._hardware_id, last_date)

            results_log = {}
            if res.get('deactivated_ids'):
                cr.execute("update sync_client_survey set active='f', server_write_date=%s where sync_server_id in %s", (res['max_date'], tuple(res['deactivated_ids'])))
                results_log['deactivated'] = cr.rowcount

            for survey_data in res.get('active', []):
                if 'id' in survey_data:
                    survey_data['sync_server_id'] = survey_data['id']
                    del(survey_data['id'])

                    survey_data['active'] = 't'
                    for field in ['included', 'excluded']:
                        list_ids = []
                        if survey_data['%s_group_txt' % field]:
                            list_ids = self.env.get('res.groups').search(cr, uid, [('name', 'in', survey_data['%s_group_txt' % field].split(','))], context=context)
                        del(survey_data['%s_group_txt' % field])
                        survey_data['%s_group_ids' % field] = [(6, 0, list_ids)]

                    local_id = survey_obj.search(cr, uid, [('sync_server_id', '=', survey_data['sync_server_id']), ('active', 'in', ['t', 'f'])], context=context)
                    if local_id:
                        survey_obj.write(cr, uid, local_id, survey_data, context=context)
                        results_log['updated'] = results_log.setdefault('updated', 0) + 1
                    else:
                        survey_obj.create(cr, uid, survey_data, context=context)
                        results_log['created'] = results_log.setdefault('created', 0) + 1
            if logger and results_log:
                logger.append(_("Survey: %s") % ', '.join(['%d %s' % (x[1], x[0]) for x in results_log.items()]))
                logger.write()

            return True
        except Exception as e:
            cr.execute("ROLLBACK TO SAVEPOINT import_surveys")
            if logger:
                logger.append("Survey error: unable to get surveys")
                logger.write()
            self._logger.error('Survey error: %s' % tools.misc.get_traceback(e))
        else:
            cr.execute("RELEASE SAVEPOINT import_surveys")

    #@sync_process('data_pull')
    @api.model
    def pull_update(self, recover=False):
        """
            Pull update
        """
        self = self.with_context({'lang': 'en_US'})
        logger = self.env.context.get('logger')
        entity = self.get_entity()
        if entity.state not in ('init', 'update_pull'):
            raise SkipStep

        if entity.state == 'init':
            self.set_last_sequence()
        sync_server_obj = self.env.get("sync.client.sync_server_connection")
        max_packet_size = sync_server_obj._get_connection_manager().max_size

        # UTP-1177: Retrieve the message ids and save into the entity at the Server side
        proxy = sync_server_obj.get_connection("sync.server.sync_manager")
        res = proxy.get_message_ids(entity.identifier, entity._hardware_id)
        if not res[0]:
            raise Exception(res[1])

        updates_count = self.retrieve_update(max_packet_size, recover=recover)
        self._logger.info("::::::::The instance " + entity.name + " pulled: " + str(res[1]) + " messages and " + str(updates_count) + " updates.")
        updates_executed = self.execute_updates()
        if updates_executed == 0 and updates_count > 0:
            self._logger.warning("No update to execute, this case should never occurs.")

        self._logger.info("Pull data :: Number of data pull: %s" % updates_count)
        if logger:
            logger.info['nb_data_pull'] = updates_count
        return True

    def set_last_sequence(self):
        entity = self.get_entity()
        proxy = self.env.get("sync.client.sync_server_connection").get_connection("sync.server.sync_manager")
        res = proxy.get_max_sequence(entity.identifier, entity._hardware_id)
        if res and res[0]:
            check_md5(res[2], res[1], _('method get_max_sequence'))
            self._logger.info("Pull data :: Last sequence: %s" % res[1])
            return entity.write({'max_update' : res[1]})
        elif res and not res[0]:
            raise Exception(res[1])
        return True

    #@sync_subprocess('data_pull_receive')
    @api.model
    def retrieve_update(self, max_packet_size, recover=False):
        logger = self.env.context.get('logger')
        updates = self.env.get(self.env.context.get('update_received_model', 'sync.client.update_received'))

        # TODO
        #init_sync = not bool(self.env.get('res.users').get_browse_user_instance(cr, uid))
        init_sync = False

        entity = self.get_entity()
        last_seq = entity.update_last
        total_max_seq = entity.max_update
        offset = (0, entity.update_offset)
        offset_recovery = entity.update_offset
        last = (last_seq >= total_max_seq)
        updates_count = 0
        logger_index = None
        proxy = self.env.get("sync.client.sync_server_connection").get_connection("sync.server.sync_manager")

        # ask only max_seq_pack sequences to the sync server
        max_seq_pack = max_packet_size

        max_seq = min(last_seq+max_seq_pack, total_max_seq)
        while max_seq <= total_max_seq:
            while not last:
                res = proxy.get_update(entity.identifier, entity._hardware_id, last_seq, offset, max_packet_size, max_seq, recover, init_sync)
                if res and res[0]:
                    if res[1]: check_md5(res[3], res[1], _('method get_update'))
                    increment_to_offset = 0
                    for package in (res[1] or []):
                        updates_count += updates.unfold_package(package)

                        if logger and updates_count:
                            if logger_index is None:
                                logger_index = logger.append()
                            logger.replace(logger_index, _("Update(s) received: %d") % updates_count)
                            logger.write()
                        if package:
                            increment_to_offset = package['offset'][1]
                            offset = (package['update_id'], 0)

                    offset_recovery += increment_to_offset
                    entity.write({'update_offset' : offset_recovery})
                    last = res[2]
                elif res and not res[0]:
                    raise Exception(res[1])
                self.env.cr.commit()

            entity.write({
                'update_offset' : 0,
                'max_update' : 0,
                'update_last' : max_seq
            })
            self.env.cr.commit()
            if max_seq == total_max_seq:
                break
            last = False
            last_seq = max_seq
            offset = (0, 0)
            offset_recovery = 0
            max_seq = min(max_seq+max_seq_pack, total_max_seq)

        """
        TODO
        instance_level = _get_instance_level()
        asset_rule_id = False
        if instance_level == 'coordo':
            rule_obj = self.env.get('sync.client.rule')
            prod_rule_id = rule_obj.search(cr, uid, [('sequence_number', '=', 604), ('model', '=', 'product.product')])
            if prod_rule_id:
                prod_rule = prod_rule_id[0]
                prod_ids = self.env.get('product.product')._get_ids_to_push(prod_rule, context=context)
                if prod_ids:
                    self.env.get('ir.model.data').mark_resend('product.product', prod_ids)
                    self.env.cr.commit()

        # product.asset: brand, serial ... updated on one side, sent update even if update received from the other side
        if instance_level == 'project':
            asset_rule_id = 558
        elif instance_level== 'coordo':
            asset_rule_id = 557

        if asset_rule_id:
            rule_obj = self.env.get('sync.client.rule')
            asset_rule_id = rule_obj.search([('sequence_number', '=', asset_rule_id), ('model', '=', 'product.asset')])
            if asset_rule_id:
                asset_rule = asset_rule_id[0]
                asset_ids = self.env.get('product.asset')._get_ids_to_push(asset_rule)
                if asset_ids:
                    self.env.get('ir.model.data').mark_resend('product.asset', asset_ids)
                    self.env.cr.commit()
        """
        trigger_analyze = self.env.get('ir.config_parameter').get_param('ANALYZE_NB_UPDATES')
        nb = 2000
        if trigger_analyze:
            nb = int(trigger_analyze)
        if updates_count >= nb:
            self._logger.info('Begin analyze sync_client_update_received')
            self.env.cr.execute('analyze sync_client_update_received')
            self._logger.info('End of analyze')

        return updates_count

    #@sync_subprocess('data_pull_execute')
    @api.model
    def execute_updates(self):
        logger = self.env.context.get('logger')
        updates = self.env.get(self.env.context.get('update_received_model', 'sync.client.update_received'))
        # get instance prioritiies
        priorities_stuff = None

        # Get a list of updates to execute
        # Warning: execution order matter
        update_ids = updates.search([('run', '=', False)], order='sequence_number, is_deleted, rule_sequence, id asc')
        update_count = len(update_ids)
        if not update_count:
            return 0

        try:
            if logger:
                logger_index = logger.append()
            done = []
            imported, deleted = 0, 0
            while update_ids:
                to_do, update_ids = update_ids[:MAX_EXECUTED_UPDATES], update_ids[MAX_EXECUTED_UPDATES:]
                messages, imported_executed, deleted_executed = \
                    to_do.execute_update()
                imported += imported_executed
                deleted += deleted_executed
                # Do nothing with messages
                done += to_do
                if logger:
                    logger.replace(logger_index, _("Update(s) processed: %d import updates + %d delete updates on %d updates") \
                                   % (imported, deleted, update_count))
                    logger.write()
                # intermittent commit
                if len(done) >= MAX_EXECUTED_UPDATES:
                    done[:] = []
                    self.env.cr.commit()
        finally:
            self.env.cr.commit()

            if logger:
                if imported or deleted:
                    logger.replace(logger_index, _("Update(s) processed: %d import updates + %d delete updates = %d total updates") % \
                                   (imported, deleted, imported+deleted))
                else:
                    logger.pop(logger_index)
                notrun_count = updates.search_count([('run','=',False)])
                if notrun_count:
                    logger.append(_("Update(s) not run left: %d") % notrun_count)
                logger.write()

        param = self.env.get('ir.config_parameter')
        if param.get_param('exec_set_journal_code_on_aji'):
            # here to process in-pipe AJI on the 1st sync after the release
            self.env.get('patch.scripts').set_journal_code_on_aji()
            param.set_param('exec_set_journal_code_on_aji', '')

        return update_count

    @sync_process('msg_push')
    def push_message(self, cr, uid, context=None):
        """
            Push message
        """
        context = context or {}
        entity = self.get_entity(cr, uid, context)
        logger = context.get('logger')
        context['lang'] = 'en_US'
        if entity.state not in ['init', 'msg_push']:
            raise SkipStep

        if entity.state == 'init':
            self.create_message(cr, uid, context=context)
            cr.commit()

        nb_msg = self.send_message(cr, uid, context=context)
        cr.commit()

        self._logger.info("Push messages :: Number of messages pushed: %d" % nb_msg)
        proxy = self.env.get("sync.client.sync_server_connection").get_connection(cr, uid, "sync.server.sync_manager")
        proxy.sync_success(entity.identifier, entity._hardware_id)
        if logger:
            logger.info['nb_msg_push'] = nb_msg
        return True

    @sync_subprocess('msg_push_create')
    def create_message(self, cr, uid, context=None):
        context = context or {}
        messages = self.env.get(context.get('message_to_send_model', 'sync.client.message_to_send'))
        rule_obj = self.env.get("sync.client.message_rule")

        to_update = {}
        messages_count = 0
        for rule in rule_obj.browse(cr, uid, rule_obj.search(cr, uid, [('type', '!=', 'USB')], context=context), context=context):
            generated_ids, ignored_ids = messages.create_from_rule(cr, uid, rule, None, context=context)
            messages_count += len(generated_ids)
            to_update.setdefault(rule.model, []).extend(generated_ids + ignored_ids)

        for model, ids in to_update.items():
            if ids:
                cr.execute('update ir_model_data set sync_date=NOW() where model=%s and res_id in %s', (model, tuple(ids)))
        return messages_count

    @sync_subprocess('msg_push_send')
    def send_message(self, cr, uid, context=None):
        context = context or {}
        logger = context.get('logger')
        messages = self.env.get(context.get('message_to_send_model', 'sync.client.message_to_send'))

        max_packet_size = self.env.get("sync.client.sync_server_connection")._get_connection_manager(cr, uid, context=context).max_size
        uuid = self.env.get('sync.client.entity').get_entity(cr, uid, context=context).identifier
        proxy = self.env.get("sync.client.sync_server_connection").get_connection(cr, uid, "sync.server.sync_manager")
        messages_max = messages.search(cr, uid, [('sent','=',False)], count=True, context=context)

        messages_count = 0
        logger_index = None
        while True:
            msg_ids, packet = messages.get_message_packet(cr, uid, max_packet_size, context=context)
            if not packet:
                break
            messages_count += len(packet)
            res = proxy.send_message(uuid, entity._hardware_id, packet, {'md5': get_md5(packet)})
            if not res[0]:
                raise Exception(res[1])
            messages.packet_sent(cr, uid, msg_ids, context=context)
            if logger and messages_count:
                if logger_index is None: logger_index = logger.append()
                logger.replace(logger_index, _("Message(s) sent: %d/%d") % (messages_count, messages_max))
                logger.write()

        if logger and messages_count:
            logger.replace(logger_index, _("Message(s) sent: %d") % messages_count)
        return messages_count
        #message_push => init

    @sync_process('msg_pull')
    def pull_message(self, cr, uid, recover=False, context=None):
        """
            Pull message
        """
        context = context or {}
        logger = context.get('logger')
        context['lang'] = 'en_US'
        proxy = self.env.get("sync.client.sync_server_connection").get_connection(cr, uid, "sync.server.sync_manager")

        entity = self.get_entity(cr, uid, context=context)

        res = proxy.get_message_rule(entity.identifier, entity._hardware_id)
        if res and not res[0]: raise Exception(res[1])
        check_md5(res[2], res[1], _('method get_message_rule'))
        self.env.get('sync.client.message_rule').save(cr, uid, res[1], context=context)

        if recover:
            proxy.message_recover_from_seq(entity.identifier, entity._hardware_id, entity.message_last)

        if not entity.state == 'init':
            raise SkipStep

        self.get_message(cr, uid, context=context)
        # UTP-1177: Reset the message ids of the entity at the server side
        proxy.reset_message_ids(entity.identifier, entity._hardware_id)
        msg_count = self.execute_message(cr, uid, context=context)
        self._logger.info("Pull message :: Number of messages pulled: %s" % msg_count)
        if logger:
            logger.info['nb_msg_pull'] = msg_count
        return True

    @sync_subprocess('msg_pull_receive')
    def get_message(self, cr, uid, context=None):
        context = context or {}
        logger = context.get('logger')
        messages = self.env.get(context.get('message_received_model', 'sync.client.message_received'))

        entity = self.get_entity(cr, uid, context)
        last_seq = entity.update_last
        messages_count = 0
        logger_index = None

        max_packet_size = self.env.get("sync.client.sync_server_connection")._get_connection_manager(cr, uid, context=context).max_size
        proxy = self.env.get("sync.client.sync_server_connection").get_connection(cr, uid, "sync.server.sync_manager")
        instance_uuid = entity.identifier

        while True:
            res = proxy.get_message(instance_uuid, entity._hardware_id,
                                    max_packet_size, last_seq)
            if not res[0]: raise Exception(res[1])

            packet = res[1]
            if not packet: break
            check_md5(res[2], packet, _('method get_message'))

            messages_count += len(packet)
            messages.unfold_package(cr, uid, packet, context=context)
            cr.commit()
            data_ids = [data['sync_id'] for data in packet]
            res = proxy.message_received_by_sync_id(instance_uuid, entity._hardware_id, data_ids, {'md5': get_md5(data_ids)})
            if not res[0]: raise Exception(res[1])

            if logger and messages_count:
                if logger_index is None: logger_index = logger.append()
                logger.replace(logger_index, _("Message(s) received: %d") % messages_count)
                logger.write()
        return messages_count

    @sync_subprocess('msg_pull_execute')
    def execute_message(self, cr, uid, context=None):
        context = context or {}
        logger = context.get('logger')
        # force user to user_sync
        uid = self.env.get('res.users')._get_sync_user_id(cr)

        messages = self.env.get(context.get('message_received_model', 'sync.client.message_received'))

        # Get the whole list of messages to execute
        # Warning: order matters
        message_ids = messages.search(cr, uid, [('run','=',False)], order='rule_sequence, id', context=context)
        messages_count = len(message_ids)
        if messages_count == 0: return 0

        try:
            if logger: logger_index = logger.append()
            messages_executed = 0
            while message_ids:
                to_do, message_ids = message_ids[:MAX_EXECUTED_MESSAGES], message_ids[MAX_EXECUTED_MESSAGES:]
                messages.execute(cr, uid, to_do, context=context)
                messages_executed += len(to_do)
                if logger is not None:
                    logger.replace(logger_index, _("Message(s) processed: %d/%d") % (messages_executed, messages_count))
                    logger.write()
                # intermittent commit
                cr.commit()
        finally:
            cr.commit()
            if logger is not None:
                logger.replace(logger_index, _("Message(s) processed: %d") % messages_count)
                notrun_count = messages.search(cr, uid, [('run', '=', False)], count=True, context=context)
                if notrun_count > 0: logger.append(_("Message(s) not run left: %d") % notrun_count)
                logger.write()
                # UTP-1200: Update already the sync_id to the logger lines for FO/PO
                logger.update_sale_purchase_logger()
        return messages_count

    def sync_threaded(self, cr, uid, recover=False, context=None):
        """
            SYNC process : usefull for scheduling
        """
        if context is None:
            context = {}
        context['sync_type'] = 'automatic'
        BackgroundProcess(cr, uid,
                          ('sync_recover_withbackup' if recover else 'sync_withbackup'),
                          context).start()
        return True

    def sync_manual_threaded(self, cr, uid, recover=False, context=None):
        if context is None:
            context = {}
        context['sync_type'] = 'manual'
        BackgroundProcess(cr, uid,
                          ('sync_manual_recover_withbackup' if recover else 'sync_manual_withbackup'),
                          context).start()
        return True

    @sync_process()
    def sync_recover(self, cr, uid, context=None):
        """
        Call both pull_all_data and recover_message functions - used in manual sync wizard
        """
        self.pull_update(cr, uid, recover=True, context=context)
        if context is None:
            context = {}
        context['restore_flag'] = True
        self.pull_message(cr, uid, recover=True, context=context)
        return True

    @sync_process()
    def sync_recover_withbackup(self, cr, uid, context=None):
        """
        Call both pull_all_data and recover_message functions - used in manual sync wizard
        """
        if context is None:
            context = {}
        context['sync_type'] = 'automatic'
        #Check for a backup before automatic sync
        self.env.get('backup.config').exp_dump_for_state(cr, uid, 'beforeautomaticsync', context=context)
        self.sync_recover(cr, uid, context=context)
        #Check for a backup after automatic sync
        self.env.get('backup.config').exp_dump_for_state(cr, uid, 'afterautomaticsync', context=context)
        return {'type': 'ir.actions.act_window_close'}

    @sync_process()
    def sync_manual_recover_withbackup(self, cr, uid, context=None):
        """
        Call both pull_all_data and recover_message functions - used in manual sync wizard
        """
        if context is None:
            context = {}
        context['sync_type'] = 'manual'
        #Check for a backup before automatic sync
        self.env.get('backup.config').exp_dump_for_state(cr, uid, 'beforemanualsync', context=context)
        self.sync_recover(cr, uid, context=context)
        #Check for a backup after automatic sync
        self.env.get('backup.config').exp_dump_for_state(cr, uid, 'aftermanualsync', context=context)
        return {'type': 'ir.actions.act_window_close'}

    @sync_process()
    def sync(self, cr, uid, context=None):
        if context is None:
            context = {}
        # is sync modules installed ?
        for sql_table, module in [('sync_client.version', 'update_client'),
                                  ('so.po.common', 'sync_so')]:
            if not self.env.get(sql_table):
                raise ValidationError("%s module is not installed ! You need to install it to be able to sync." % module)
        # US_394: force synchronization lang to en_US
        context['lang'] = 'en_US'
        logger = context.get('logger')
        self._logger.info("Start synchronization")

        version_instance_module = self.env.get('sync.version.instance.monitor')
        version_data = {}
        try:
            backup_config_id = self.env.get('ir.model.data').get_object_reference(cr, uid, 'sync_client', 'backup_config_default')[1]
            config_obj = self.env.get('backup.config')
            version = config_obj.get_server_version(cr, uid, context=context)

            postgres_disk_space = version_instance_module._get_default_postgresql_disk_space(cr, uid)
            unifield_disk_space = version_instance_module._get_default_unifield_disk_space(cr, uid)
            version_data = {
                'version': version,
                'postgresql_disk_space': postgres_disk_space,
                'unifield_disk_space': unifield_disk_space,
                'machine': platform.machine(),
                'platform': platform.platform(),
                'processor': platform.processor(),
            }

            config_data = config_obj.read(cr, uid, backup_config_id, ['backup_type', 'wal_directory', 'ssh_config_dir', 'basebackup_date', 'rsync_date'], context=context)
            del config_data['id']
            version_data.update(config_data)


        except Exception:
            cr.rollback()
            logging.getLogger('version.instance.monitor').exception('Cannot generate instance monitor data')
            # do not block sync
            pass

        try:
            # list VI jobs
            job_details = []
            nb_late = 0
            now = time.strftime('%Y-%m-%d %H:%M:%S')

            dt_format = '%d/%b/%Y %H:%M'
            for auto_job in ['automated.export', 'automated.import']:
                job_obj = self.env.get(auto_job)
                job_ids = job_obj.search(cr, uid, [('active', '=', True), ('cron_id', '!=', False)], context=context)
                if job_ids:
                    end_time_by_job = {}
                    job_field = "%s_id" % auto_job.split('.')[-1]
                    cr.execute("select "+job_field+", max(end_time) from "+auto_job.replace('.', '_')+"_job where "+job_field+" in %s and state in ('done', 'error') group by "+job_field, (tuple(job_ids), )) # not_a_user_entry
                    for end in cr.fetchall():
                        end_time_by_job[end[0]] = end[1] and time.strftime(dt_format, time.strptime(end[1], '%Y-%m-%d %H:%M:%S'))

                    for job in job_obj.browse(cr, uid, job_ids, fields_to_fetch=['name', 'cron_id', 'last_exec'], context=context):
                        if job.cron_id.nextcall < now:
                            nb_late += 1
                            job_name = '%s*' % job.name
                        else:
                            job_name = job.name

                        job_details.append('%s: %s' % (job_name, end_time_by_job.get(job.id, 'never')))

            version_data['nb_late_vi'] = nb_late
            version_data['vi_details'] = "\n".join(job_details)
            version_instance_module.create(cr, uid, version_data, context=context)
        except Exception:
            cr.rollback()
            logging.getLogger('version.instance.monitor').exception('Cannot generate instance monitor data')
        self.check_user_rights(cr, uid, context=context)
        self.get_surveys(cr, uid, context=context)
        self.set_rules(cr, uid, context=context)
        self.pull_update(cr, uid, context=context)
        self.pull_message(cr, uid, context=context)
        self.push_update(cr, uid, context=context)
        self.push_message(cr, uid, context=context)
        nb_msg_not_run = self.env.get('sync.client.message_received').search(cr, uid, [('run', '=', False)], count=True)
        nb_data_not_run = self.env.get('sync.client.update_received').search(cr, uid, [('run', '=', False)], count=True)
        if logger:
            logger.info['nb_msg_not_run'] = nb_msg_not_run
            logger.info['nb_data_not_run'] = nb_data_not_run

        self._logger.info('Not run updates : %d' % (nb_data_not_run, ))
        self._logger.info('Not run messages : %d' % (nb_msg_not_run, ))
        self._logger.info("Synchronization successfully done")
        if self.env.get('wizard.hq.report.oca').launch_auto_export(cr, uid, context=context):
            if logger:
                logger_index = logger.append()
                logger.replace(logger_index, 'Processing Export to HQ system (OCA) - Not yet exported')
                logger.write()
            self._logger.info('Processing Export to HQ system (OCA) - Not yet exported')
        elif self.env.get('ocp.export.wizard').launch_auto_export(cr, uid, context=context):
            if logger:
                logger_index = logger.append()
                logger.replace(logger_index, 'Processing Export to HQ system (OCP)')
                logger.write()
            self._logger.info('Processing Export to HQ system (OCP)')
        return True

    @sync_process()
    def sync_withbackup(self, cr, uid, context=None):
        """
        Call both pull_all_data and recover_message functions - used in manual sync wizard
        """
        if context is None:
            context = {}
        context['sync_type'] = 'automatic'
        #Check for a backup before automatic sync
        self.env.get('backup.config').exp_dump_for_state(cr, uid, 'beforeautomaticsync', context=context)
        self.sync(cr, uid, context=context)
        #Check for a backup after automatic sync
        logger = context.get('logger')
        if logger:
            logger.ok_before_last_dump = True
        self.env.get('backup.config').exp_dump_for_state(cr, uid, 'afterautomaticsync', context=context)
        return {'type': 'ir.actions.act_window_close'}

    @sync_process()
    def sync_manual_withbackup(self, cr, uid, context=None):
        """
        Call both pull_all_data and recover_message functions - used in manual sync wizard
        """
        #Check for a backup before automatic sync
        if context is None:
            context = {}
        context['sync_type'] = 'manual'
        self.env.get('backup.config').exp_dump_for_state(cr, uid, 'beforemanualsync', context=context)
        self.sync(cr, uid, context=context)
        #Check for a backup after automatic sync
        logger = context.get('logger')
        if logger:
            logger.ok_before_last_dump = True
        self.env.get('backup.config').exp_dump_for_state(cr, uid, 'aftermanualsync', context=context)
        return {'type': 'ir.actions.act_window_close'}

    def get_upgrade_status(self, cr, uid, context=None):
        return ""

    # Check if lock can be acquired or not
    def is_syncing(self, raise_on_syncing=False):
        acquired = self.sync_lock[self.env.cr.dbname].acquire(blocking=False)
        if not acquired:
            if raise_on_syncing:
                raise already_syncing_error
            return True
        self.sync_lock[self.env.cr.dbname].release()
        self.aborting = False
        return False

    def get_status(self, cr, uid, context=None):
        connection_obj = self.env.get('sync.client.sync_server_connection')
        if not connection_obj.is_connected:
            login, password = connection_obj._info_connection_from_config_file(cr)
            if login == -1 or not login or not password:
                return _("Not Connected")

        if self.is_syncing():
            if self.aborting:
                return _("Aborting...")
            return _("Syncing...")

        monitor = self.env.get("sync.monitor")
        last_log = monitor.last_status
        if last_log:
            return _("Last Sync: %s at %s, Not run upd: %s, Not run msg: %s") \
                % (_(monitor.status_dict[last_log[0]]), last_log[1], last_log[2], last_log[3])
        return _("Connected")

    def update_nb_shortcut_used(self, cr, uid, nb_shortcut_used, context=None):
        '''
        if the current have used some shorcut, update his counter and last date of use accordingly
        '''
        if context is None:
            context = {}
        if not nb_shortcut_used:
            return True
        user_obj = self.env.get('res.users')
        current_date = datetime.now()
        previous_nb_shortcut_used = user_obj.read(cr, uid, uid,
                                                  ['nb_shortcut_used'],
                                                  context=context)['nb_shortcut_used']
        total_shortcut_used = previous_nb_shortcut_used + nb_shortcut_used
        user_obj.write(cr, uid, uid, {'last_use_shortcut': current_date,
                                      'nb_shortcut_used': total_shortcut_used,
                                      }, context=context)
        return True

    def display_shortcut_message(self, cr, uid, context=None):
        '''
        return True if the message should be displayed, False otherwize.
        random is used not display all the time the message, but 1 out of 10.
        '''
        if context is None:
            context = {}
        user_obj = self.env.get('res.users')
        result = user_obj.read(cr, uid, uid,
                               ['nb_shortcut_used',
                                'last_use_shortcut'],
                               context=context)
        if result['nb_shortcut_used'] and result['nb_shortcut_used'] > 100:
            # once the user have used the shortcut a lot of times, do not
            # bother him with warning message
            return False
        if not result['last_use_shortcut']:
            # user have never used the shortcut
            return random() < 0.1
        last_date = result['last_use_shortcut']
        last_date = datetime.strptime(last_date[:19],'%Y-%m-%d %H:%M:%S')
        current_date = datetime.now()
        if current_date - last_date > timedelta(days=1):
            # the user didn't use the shortcut since long time
            return random() < 0.1
        return False

    def interrupt_sync(self, cr, uid, context=None):
        if self.is_syncing():
            #try:
            #    self._renew_sync_lock()
            #except StandardError:
            #    return False
            self.aborting = True
            # US-2306 : before to close the cursor, clear the _get_id caches
            self.env.get('ir.model.data')._get_id.clear_cache(cr.dbname)
            self.sync_cursor.close(True)
        return True

    def clean_updates(self, cr, uid):
        '''delete old updates older than 6 months
        '''
        nb_month_to_clean = 6

        # delete sync_client_update_received older than 6 month
        cr.execute("""DELETE FROM sync_client_update_received
        WHERE create_date < now() - interval '%s month' AND
        execution_date IS NOT NULL AND run='t'""", (nb_month_to_clean,))
        deleted_update_received = cr.rowcount
        self._logger.info('clean_updates method has deleted %d sync_client_update_received' % deleted_update_received)

        # delete sync_client_update_to_send older than 6 month
        cr.execute("""DELETE FROM sync_client_update_to_send
        WHERE create_date < now() - interval '%s month' AND
        sent_date IS NOT NULL AND sent='t'""", (nb_month_to_clean,))
        deleted_update_to_send = cr.rowcount
        self._logger.info('clean_updates method has deleted %d sync_client_update_to_send' % deleted_update_to_send)

        self._logger.info('Begin analyze sync_client_update_to_send')
        cr.execute('analyze sync_client_update_to_send')
        self._logger.info('End analyze, begin analyze sync_client_update_received')
        cr.execute('analyze sync_client_update_received')
        self._logger.info('End analyze')

