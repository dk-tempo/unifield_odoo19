from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductColdChain(models.Model):
    _name = 'product.cold_chain'
    _description = 'Product Thermosensitivity'
    _order = 'id'

    code = fields.Char(string="Code", size=256)
    ud_code = fields.Char(string="Code", size=256)
    name = fields.Char(string="Name", translate=True, size=256, required=True)
    cold_chain = fields.Boolean(string="Cold Chain", default=False)
    mapped_to = fields.Many2one(string="Mapped to", comodel_name="product.cold_chain", ondelete="set null", readonly=True)

    def unlink(self):
        # Raise an error if the cold chain is used in a product
        if self.env['product.product'].search([('cold_chain', 'in', self.ids)]):
            raise ValidationError(_('You cannot delete this cold chain because it\'s used at least in one product'))
        return super(ProductColdChain, self).unlink()
