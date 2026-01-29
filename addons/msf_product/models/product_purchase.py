from odoo import api, fields, models

# Mock class used to test the msf_search_panel module

class ProductPurchase(models.Model):
    _name = "product.purchase"
    _description = "Product Purchase"



    name = fields.Char(string="Name")
    line_ids = fields.One2many(string="Product Lines", comodel_name="product.purchase.line",
                               inverse_name="product_purchase_id")
