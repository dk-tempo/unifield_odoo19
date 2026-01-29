from odoo import api, fields, models

# Mock class used to test the msf_search_panel module

class ProductPurchaseLine(models.Model):
    _name = "product.purchase.line"
    _description = "Product Purchase Line"

    name = fields.Char(string="Description")
    product_id = fields.Many2one(string="Product", comodel_name="product.product")
    product_purchase_id = fields.Many2one(string="Purchase", comodel_name="product.purchase")
