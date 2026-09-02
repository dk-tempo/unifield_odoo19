from odoo import api, fields, models


class ProductSectionCode(models.Model):
    _name = 'product.supply.source'
    _description = 'product.supply.source'
    _order = 'id'
    _rec_name = 'source'

    source = fields.Char(string="Supply source", size=32)
