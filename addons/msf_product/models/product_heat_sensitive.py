from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductHeatSensitive(models.Model):
    _name = 'product.heat_sensitive'
    _description = 'Temperature Sensitive Product'
    _order = 'code desc'

    code = fields.Char(string="Code", size=256)
    name = fields.Char(string="Name", translate=True, size=256, required=True)
    active = fields.Boolean(string="Active", default=True)

    def unlink(self):
        # Raise an error if the sensitivity is used in a product
        if self.env['product.product'].search([('heat_sensitive_item', 'in', self.ids)]):
            raise ValidationError(_('You cannot delete this heat sensitive because it\'s used at least in one product'))
        return super(ProductHeatSensitive, self).unlink()
