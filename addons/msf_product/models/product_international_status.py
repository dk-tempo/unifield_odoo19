from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductInternationalStatus(models.Model):
    _name = 'product.international.status'
    _description = 'Product Creators'
    _order = 'id'

    code = fields.Char(string="Code", size=256)
    name = fields.Char(string="Name", translate=True, size=256, required=True)
    no_external = fields.Boolean(string="External partners orders")
    no_esc = fields.Boolean(string="ESC partners orders")
    no_internal = fields.Boolean(string="Internal partners orders")
    no_consumption = fields.Boolean(string="Consumption")
    no_storage = fields.Boolean(string="Storage")

    def unlink(self):
        # Raise an error if the creator is used in a product
        if self.env['product.product'].search([('international_status', 'in', self.ids)]):
            raise ValidationError(_('You cannot delete this product creator because it\'s used at least in one product'))

        if self.env.ref('msf_product.int_1') and self.env.ref('msf_product.int_1').id in self.ids:
            raise osv.except_osv(_('Error'), _('You cannot remove the \'ITC\' international status because it\'s a system value'))
        if self.env.ref('msf_product.int_5') and self.env.ref('msf_product.int_5').id in self.ids:
            raise osv.except_osv(_('Error'), _('You cannot remove the \'Temporary\' international status because it\'s a system value'))

        return super(ProductInternationalStatus, self).unlink()
