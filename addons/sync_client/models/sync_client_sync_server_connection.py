# -*- coding: utf-8 -*-

from datetime import datetime, timedelta

from odoo import api, fields, tools, models, _
from odoo.exceptions import UserError, ValidationError
import uuid
import logging

from threading import Thread, RLock, Lock
import functools
from . import rpc

_logger = logging.getLogger(__name__)

class Connection(models.Model):
    _name = 'sync.client.sync_server_connection'
    _description = 'Connection to sync server information and tools'
    _order = 'id'

    _uid = {}
    _password = {}

    active = fields.Boolean(string="Active", default=True)
    host = fields.Char(string="Host", size=256, required=True, help="Synchronization server host name", default="sync.unifield.net")
    port = fields.Integer(string="Port", help="Synchronization server connection port", default=443)
    protocol = fields.Selection(string="Protocol", selection=[('xmlrpc', 'XMLRPC'), ('gzipxmlrpcs', 'secured compressed XMLRPC')], help="Changing protocol may imply changing the port number", default="gzipxmlrpcs")
    database = fields.Char(string="Database Name", size=64, default="SYNC_SERVER")
    login = fields.Char(string="Login on synchro server", size=64, default="admin")
    uid = fields.Char(string="Uid on synchro server", compute="_get_uid", readonly=True)
    password = fields.Char(string="Password", compute="_get_password", inverse="_set_password")
    state = fields.Char(string="State", compute="_get_state", readonly=True)
    max_size = fields.Integer(string="Max Packet Size", default=500)
    timeout = fields.Float(string="Timeout", default=600.0)
    netrpc_retry = fields.Integer(string="NetRPC retry", default=10)
    xmlrpc_retry = fields.Integer(string="XmlRPC retry", default=10)
    automatic_patching = fields.Boolean(string="Silent Upgrade", help="Enable this if you want to automatically install patches during these hours.", default=False,)
    automatic_patching_hour_from = fields.Float(string="Upgrade from", help="Enable upgrade from this time")
    automatic_patching_hour_to = fields.Float(string="Upgrade until", help="Enable upgrade unitl this time")

    _active = models.Constraint(
        'UNIQUE(active)',
        'The connection parameter is unique; you cannot create a new one'
    )


    def _auto_init(self):
        super()._auto_init()
        if not self.search_count([]):
            self.create({})


    def _is_connected(self):
        return Connection._uid.get(self.env.cr.dbname) > 0

    is_connected = property(_is_connected)

    def _get_state(self):
        r = "Connected" if Connection._uid.get(self.env.cr.dbname) else "Disconnected"
        for s in self:
            s.state = r

    def _get_password(self):
        for s in self:
            s.password = Connection._password.get(self.env.cr.dbname)

    def _set_password(self):
        Connection._password[self.env.cr.dbname] = self.password

    def _get_uid(self):
        for s in self:
            s.uid = Connection._uid.get(self.env.cr.dbname)

    def unlink(self):
        Connection._uid[self.env.cr.dbname] = False
        return super().unlink(self)

    def on_change_upgrade_hour(self, cr, uid, ids, automatic_patching_hour_from, automatic_patching_hour_to):
        # TODO
        """ Finds default stock location id for changed warehouse.
        @param warehouse_id: Changed id of warehouse.
        @return: Dictionary of values.
        """
        result = {'value': {}, 'warning': {}}
        values_dict = {
            'automatic_patching_hour_from':automatic_patching_hour_from,
            'automatic_patching_hour_to':automatic_patching_hour_to
        }
        for name, value in list(values_dict.items()):
            if value < 0:
                result.setdefault('value', {}).update({name: 0})
            if value >= 24:
                result.setdefault('value', {}).update({name: 23.98}) # 23.98 == 23h59
        return result

    def is_automatic_patching_allowed(self, cr, uid, date=None, automatic_patching=None,
                                      hour_from=None, hour_to=None, context=None):
        # TODO
        """
        return True if the passed date is in the range of hour_from, hour_to
        False othewise
        If no date is passed as parameter, datetime.today() is used
        """
        connection = self._get_connection_manager(cr, uid)
        if automatic_patching is None:
            automatic_patching = connection.automatic_patching
        if not automatic_patching:
            return False

        if date is None:
            date = datetime.today()
        if isinstance(date, str):
            date = datetime.strptime(date, '%Y-%m-%d %H:%M')

        if not hour_from:
            hour_from = connection.automatic_patching_hour_from
        if not hour_to:
            hour_to = connection.automatic_patching_hour_to

        hour_from_decimal = int(math.floor(abs(hour_from)))
        min_from_decimal = int(round(abs(hour_from)%1+0.01,2) * 60)
        hour_to_decimal = int(math.floor(abs(hour_to)))
        min_to_decimal = int(round(abs(hour_to)%1+0.01,2) * 60)

        from_date = datetime(date.year, date.month, date.day,
                             hour_from_decimal, min_from_decimal)
        to_date = datetime(date.year, date.month, date.day, hour_to_decimal,
                           min_to_decimal)

        # from_date and to_date are not the same day:
        if from_date > to_date:
            # case 1: the from date is in the past
            # ex. it is 3h, from_date=19h, to_date=7h
            if from_date > date:
                from_date = from_date - timedelta(days=1)

            # case 2: the to_date is in the future
            # ex. it is 20h, from_date=19h, to_date=7h
            elif date > to_date:
                to_date = to_date + timedelta(days=1)

        return date > from_date and date < to_date

    @api.model
    def _get_connection_manager(self):
        c = self.search([])
        if not c:
            raise UserError("Connection manager not set!")
        return c[0]

    def connector_factory(self):
        # xmlrpc now does gzip by default
        if self.protocol == 'xmlrpc' or self.protocol == 'gzipxmlrpc':
            connector = rpc.XmlRPCConnector(self.host, self.port, timeout=self.timeout, retry=self.xmlrpc_retry)
        elif self.protocol == 'xmlrpcs' or self.protocol == 'gzipxmlrpcs':
            connector = rpc.SecuredXmlRPCConnector(self.host, self.port, timeout=self.timeout, retry=self.xmlrpc_retry)
        else:
            raise UserError('Unknown protocol: %s' % self.protocol)
        return connector

    def _info_connection_from_config_file(self, cr):
        login = tools.config.get('sync_user_login')
        if login == 'admin':
            if not self.search_exist(cr, 1, [('host', 'in', ['127.0.0.1', 'localhost'])]):
                login = -1
        return (login, tools.config.get('sync_user_password'))

    def get_connection_from_config_file(self, cr, uid, ids=None, context=None):
        '''
        get credentials from config file if any and try to connect to the sync
        server with them. Return True if it has been connected using this
        credentials, False otherwise
        '''
        logger = logging.getLogger('sync.client')
        if not self.is_connected:
            login, password = self._info_connection_from_config_file(cr)
            if login == -1:
                raise AdminLoginException
            if login and password:
                # write this credentials in the connection manager to be
                # consistent with the credentials used for the current
                # connection and what is in the connection manager
                connection_ids = self.search(cr, 1, [])
                if connection_ids:
                    logger.info('Automatic set up of sync connection credentials')
                    data_to_write = {
                        'login': login,
                        'password': password,
                    }
                    self.write(cr, 1, connection_ids, data_to_write)
                    cr.commit()
                return self.connect(cr, 1, password=password, login=login)
        return False

    @api.model
    def connect(self, password=None, login=None, context=None):
        """
        connect the instance to the SYNC_SERVER instance for synchronization
        """
        if Connection._uid.get(self.env.cr.dbname):
            return True
        try:
            con = self._get_connection_manager()
            sync_args = {
                'client_name': self.env.cr.dbname,
                'server_name': con.database,
            }
            _logger.info('Client \'%(client_name)s\' attempts to connect to sync. server \'%(server_name)s\'' % sync_args)
            connector = con.connector_factory()
            if not Connection._password.get(self.env.cr.dbname):
                if password is not None:
                    Connection._password[self.env.cr.dbname] = password
                    con.password = password
                else:
                    Connection._password[self.env.cr.dbname] = tools.config.get('sync_user_password', con.login)
            if login is None:
                login = con.login
            cnx = rpc.Connection(connector, con.database, login, Connection._password[self.env.cr.dbname])
            if cnx.user_id:
                Connection._uid[self.env.cr.dbname] = cnx.user_id
            else:
                raise USerError("Not connected to server. Please check password and connection status in the Connection Manager")

            # Update the credentials in the config file if they are empty
            """
            TODO
            save_sync_login, save_sync_pass = False, False
            if login and not tools.config.get('sync_user_login'):
                tools.config['sync_user_login'] = login
                save_sync_login = True
            if self._password and not tools.config.get('sync_user_password'):
                tools.config['sync_user_password'] = self._password
                save_sync_pass = True
            if save_sync_login or save_sync_pass:
                tools.config.save_sync_credentials(login, self._password)
            """
        except Exception:
            raise

        _logger.info('Client \'%(client_name)s\' succesfully connected to sync. server \'%(server_name)s\'' % sync_args)
        return True

    def action_connect(self):
        self.connect()
        return {}

    @api.model
    def get_connection(self, model):
        """
            @return: the proxy to call distant method specific to a model
            @param model: the model name we want to call remote method
        """
        con = self._get_connection_manager()
        connector = con.connector_factory()
        cnx = rpc.Connection(connector, con.database, con.login, con.password, con.uid)
        return rpc.Object(cnx, model)

    @api.model
    def disconnect(self, cr, uid, context=None):
        con = self._get_connection_manager()
        sync_args = {
            'client_name': cr.dbname,
            'server_name': con.database,
        }
        if not self.pool.get('sync.client.entity').interrupt_sync(cr, uid, context=context):
            _logger.warning('Error during the disconnection of client \'%(client_name)s\'' % sync_args)
            return False
        Connection._uid[self.env.cr.dbname] = False
        _logger.info('Client \'%(client_name)s\' succesfully disconnected from the sync. server \'%(server_name)s\'' % sync_args)
        return True

    def action_disconnect(self):
        self.disconnect()
        return {}

    def write(self, vals):
        # reset connection flag when connection data changed
        connection_property_list = [
            'database',
            'host',
            'login',
            'max_size',
            'netrpc_retry',
            'password',
            'port',
            'protocol',
            'timeout',
            'xmlrpc_retry'
        ]

        for key in connection_property_list:
            if vals.get(key) != getattr(self, key):
                Connection._uid[self.env.cr.dbname] = False
                break

        """
        TODO
        # check the new properties match the automatic sync task
        if set(('automatic_patching', 'automatic_patching_hour_from',
                'automatic_patching_hour_to')).issubset(list(vals.keys())) and\
                vals['automatic_patching']:

            try:
                model, auto_sync_id = self.pool.get('ir.model.data').get_object_reference(cr, uid,
                                                                                          'sync_client', 'ir_cron_automaticsynchronization0')
                cron_obj = self.pool.get(model)
                sync_cron = cron_obj.read(cr, uid, auto_sync_id,
                                          ['nextcall','interval_type',
                                           'interval_number',
                                           'active', 'numbercall'],
                                          context=context)
                if not sync_cron['active']:
                    raise osv.except_osv(_('Error!'),
                                         _('Automatic Synchronization must be '
                                           'activated to perform Silent Upgrade'))
                try:
                    cron_obj.check_upgrade_time_range(cr, uid,
                                                      sync_cron['nextcall'], sync_cron['interval_type'],
                                                      sync_cron['interval_number'],
                                                      vals['automatic_patching_hour_from'],
                                                      vals['automatic_patching_hour_to'],
                                                      vals['automatic_patching'], context=context)
                except osv.except_osv:
                    nextcall_time = datetime.strptime(sync_cron['nextcall'],
                                                      '%Y-%m-%d %H:%M:%S').strftime('%H:%M')
                    raise osv.except_osv(_('Error!'),
                                         _('Silent Upgrade time range must include '
                                           'the Automatic Synchronization time (%s)') % nextcall_time)
            except ValueError:
                pass  # the reference don't exists
        """
        return super().write(vals)

    def change_host(self, cr, uid, ids, host, proto, context=None):
        if host in ('127.0.0.1', 'localhost'):
            return self.change_protocol(cr, uid, ids, host, proto, context=context)
        return {}

    def change_protocol(self, cr, uid, ids, host, proto, context=None):
        xmlrpc = 8069
        xmlrpcs = 443
        netrpc = 8070
        if host in ('127.0.0.1', 'localhost'):
            xmlrpc = tools.config.get('xmlrpc_port')
            netrpc = tools.config.get('netrpc_port')
            # For xmlrpcs, we keep the default value (443) because this does
            # not make much sense anyway to have SSL over localhost (won't have
            # a valid certificate)
        ports = {
            'xmlrpc': xmlrpc,
            'gzipxmlrpc': xmlrpc,
            'xmlrpcs': xmlrpcs,
            'gzipxmlrpcs': xmlrpcs,
            'netrpc': netrpc,
            'netrpc_gzip': netrpc,
        }
        if ports.get(proto):
            return {'value': {'port': ports[proto]}}
        return {}

