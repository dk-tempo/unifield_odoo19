from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
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
    last_update_date = fields.Date(string="Last update date", readonly=True, copy=False)
    standard_list_ok = fields.Boolean(string="Standard List")
    order_list_print_ok = fields.Boolean(string="Order list print")
    reviewer_id = fields.Many2one(string="Reviewed by", comodel_name="res.users", ondelete="set null", readonly=True, copy=False)
    parent_id = fields.Many2one(string="Parent list", comodel_name="product.list", ondelete="set null")
    # warehouse_id = fields.Many2one(string="Warehouse", comodel_name="stock.warehouse", ondelete="set null")
    # location_id = fields.Many2one(string="Stock Location", comodel_name="stock.location", ondelete="set null")
    product_ids = fields.One2many(string="Products", comodel_name="product.list.line", inverse_name="list_id")
    old_product_ids = fields.One2many(string="Old Products", comodel_name="old.product.list.line",
                                      inverse_name="list_id")
    nb_products = fields.Integer(string="# of products", compute="_get_nb_products", readonly=True)
    # TODO: 'in_any_product_list' used in _where_calc
    real_product_ids = fields.Many2many(string="Products", compute="_get_real_product_ids",
                                        search="_search_real_product_ids", comodel_name="product.product",
                                        readonly=True, domain="[('in_any_product_list', '=', True)]")
    alert_msl_mml = fields.Char(string="Contains non-conform MML/MSL", compute="_get_header_msl_mml_alert", readonly=True)
    from_sync = fields.Boolean(string="Created by Sync", compute="_is_from_sync", readonly=True)

    _name_uniq = models.Constraint('unique(name)', 'A list or sublist with the same name already exists in the system!')

    # Compute methods
    def _get_nb_products(self):
        """
        Returns the number of products on the list
        """
        for list in self:
            list.nb_products = len(list.product_ids)

    def _get_real_product_ids(self):
        res = {}
        self.env.cr.execute('SELECT list_id, ARRAY_AGG(name) FROM product_list_line WHERE list_id IN %s GROUP BY list_id',
                            (tuple(self.ids),))
        for x in self.env.cr.fetchall():
            res[x[0]] = x[1]

        for list in self:
            list.real_product_ids = list.id in res and res[list.id] or []

    def _get_header_msl_mml_alert(self):
        """"""
        for list in self:
            list.alert_msl_mml = ""

    def _is_from_sync(self):
        """"""
        for list in self:
            list.from_sync = False

    # Search methods
    def _search_real_product_ids(self, operator, value):
        return [('product_ids.name', operator, value)]

    # Onchange methods
    @api.onchange('parent_id')
    def _onchange_parent_id(self):
        """
        Check if all products are in the parent list
        """
        if self.parent_id and set(self.product_ids.name.ids).difference(self.parent_id.product_ids.name.ids):
            raise UserError(_('The selected parent list is not consistent with the products in the list. Please select another parent list or remove the products of the list that are not in the selected parent list before select the parent list.'))

    def write(self, values):
        values.update({
            'reviewer_id': self.env.user.id,
            'last_update_date': time.strftime('%Y-%m-%d'),
        })

        if values.get('type') == 'list':
            values['parent_id'] = False

        return super(ProductList, self).write(values)

    def unlink(self):
        for prod_list in self:
            if not self.env.context.get('sync_update_execution') and prod_list.from_sync:
                raise ValidationError(_('You can not delete a synced product list created in another instance'))

        return super(ProductList, self).unlink()


class ProductListLine(models.Model):
    _name = 'product.list.line'
    _description = 'Line of product list'
    _order = 'ref'

    name = fields.Many2one(string="Product Description", comodel_name="product.product", ondelete="restrict",
                           required=True)
    list_id = fields.Many2one(string="List", comodel_name="product.list", ondelete="cascade")
    ref = fields.Char(string="Product Code", related="name.default_code", store=True, size=64, readonly=True)
    desc = fields.Char(string="Product Description", related="name.name", store=True, size=128, readonly=True)
    comment = fields.Char(string="Comment", size=256)
    mml_status = fields.Selection(string="MML", compute="_get_std_mml_status",
                                  selection=[('T', 'Yes'), ('F', 'No'), ('na', ' ')], readonly=True, default="na")
    msl_status = fields.Selection(string="MSL", compute="_get_std_mml_status",
                                  selection=[('T', 'Yes'), ('F', 'No'), ('na', ' ')], readonly=True, default="na")

    @api.constrains('name', 'list_id')
    def _check_prod_uniq(self):
        """
        check if product already exists in the product list
        """
        if self._name != 'old.product.list.line' and not self.env.context.get('sync_update_execution'):
            for list_line in self:
                if self.search([('id', '!=', list_line.id), ('name', '=', list_line.name.id),
                                ('list_id', '=', list_line.list_id.id)]):
                    raise ValidationError('This product cannot be added as it already exists in this list')

    # Compute methods
    def _get_std_mml_status(self):
        """"""
        for list_line in self:
            list_line.mml_status = 'na'
            list_line.msl_status = 'na'

    def unlink(self, extra_comment=None):
        """
        Create old product list line on product list line deletion
        """
        opll_obj = self.env['old.product.list.line']
        if not self.env.context.get('import_error', False):
            for list_line in self:
                if list_line.list_id and list_line.name:
                    opll_obj.create({
                        'removal_date': time.strftime('%Y-%m-%d'),
                        'comment': extra_comment or list_line.comment or '',
                        'name': list_line.name.id,
                        'list_id': list_line.list_id.id,
                    })

        return super(ProductListLine, self).unlink()


class OldProductListLine(models.Model):
    _name = 'old.product.list.line'
    _inherit = 'product.list.line'
    _description = 'Old line of product list'
    _order = 'removal_date'

    ref = fields.Char(string="Product Code", related="name.default_code", store=True, size=64, readonly=True)
    desc = fields.Char(string="Product Description", related="name.name", store=True, size=128, readonly=True)
    removal_date = fields.Date(string="Removal date", readonly=True, default=lambda *a: time.strftime('%Y-%m-%d'))
