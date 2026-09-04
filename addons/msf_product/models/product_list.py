from odoo import api, fields, models
import time


class ProductList(models.Model):
    _name = 'product.list'
    _description = 'Products list'
    _order = 'id'

    name = fields.Char(string="Name", size=128, required=True)
    ref = fields.Char(string="Ref.", size=128)
    type = fields.Selection(string="Type", selection=[('list', 'List'), ('sublist', 'Sublist')], required=True)
    creator = fields.Selection(string="Creator", selection=[('hq', 'HQ'), ('coordo', 'Coordination'), ('project', 'Project'),
                                                            ('temp', 'Temporary')], required=True, default=lambda *a: 'temp', )
    description = fields.Char(string="Description", size=256)
    creation_date = fields.Date(string="Creation date", readonly=True, default=lambda *a: time.strftime('%Y-%m-%d'), )
    last_update_date = fields.Date(string="Last update date", readonly=True)
    standard_list_ok = fields.Boolean(string="Standard List")
    order_list_print_ok = fields.Boolean(string="Order list print")
    reviewer_id = fields.Many2one(string="Reviewed by", comodel_name="res.users", ondelete="set null", readonly=True)
    parent_id = fields.Many2one(string="Parent list", comodel_name="product.list", ondelete="set null")
    # warehouse_id = fields.Many2one(string="Warehouse", comodel_name="stock.warehouse", ondelete="set null")
    # location_id = fields.Many2one(string="Stock Location", comodel_name="stock.location", ondelete="set null")
    product_ids = fields.One2many(string="Products", comodel_name="product.list.line", inverse_name="list_id")
    # old_product_ids = fields.One2many(string="Old Products", comodel_name="old.product.list.line",
    #                                   inverse_name="list_id")
    nb_products = fields.Integer(string="# of products", compute="_get_nb_products", readonly=True)
    # TODO: 'in_any_product_list' used in _where_calc
    real_product_ids = fields.Many2many(string="Products", compute="_get_real_product_ids",
                                        search="_search_real_product_ids", comodel_name="product.product",
                                        readonly=True, domain="[('in_any_product_list', '=', True)]")
    alert_msl_mml = fields.Char(string="Contains non-conform MML/MSL", compute="_get_header_msl_mml_alert", readonly=True)
    from_sync = fields.Boolean(string="Created by Sync", compute="_is_from_sync", readonly=True)

    # Compute methods
    def _get_nb_products(self):
        """"""
        for record in self:
            record.nb_products = 0

    def _get_real_product_ids(self):
        """"""
        for record in self:
            record.real_product_ids = None

    def _get_header_msl_mml_alert(self):
        """"""
        for record in self:
            record.alert_msl_mml = ""

    def _is_from_sync(self):
        """"""
        for record in self:
            record.from_sync = False

    # Search methods
    def _search_real_product_ids(self, operator, value):
        """"""
        return [('id', operator, value)]
