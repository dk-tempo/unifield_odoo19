from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductStatus(models.Model):
    _name = 'product.status'
    _description = 'Product Status'

    code = fields.Char(string='Code', size=256)
    name = fields.Char(string='Name', size=256, required=True, translate=1)
    no_external = fields.Boolean(string='External partners orders')
    no_esc = fields.Boolean(string='ESC partners orders')
    no_internal = fields.Boolean(string='Internal partners orders')
    no_consumption = fields.Boolean(string='Consumption')
    no_storage = fields.Boolean(string='Storage')
    active = fields.Boolean('Active', default=True)
    mapped_to = fields.Many2one(comodel_name='product.status', string='Replaced by')

    def unlink(self):
        # Raise an error if the status is used in a product
        if self.env['product.product'].search([('state', 'in', self.ids)]):
            raise ValidationError(_('You cannot delete this status because it\'s used at least in one product'))
        return super(ProductStatus, self).unlink()
