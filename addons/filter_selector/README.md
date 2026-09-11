# Filter Selector

Odoo 19 (OWL) widget that adds quick filters, free-text search, and bulk
actions to fields displayed as lists inside a form.

## Why this module

Sublists inside a form do not provide a native mechanism
for quick filtering or multiple selection. This module fills that gap
without modifying Odoo's core: everything is added through an optional field
widget.

## Usage

On any field in a form view, add the
`widget="filter_selector_one2many"` attribute and configure the options:

```xml
<field name="order_line" widget="filter_selector_one2many"
       options="{
            'enable_selection': true
            'filter_options': [
                ['All', []],
                ['Draft only', [['state','=','draft']]],
                ['Not Cancelled', [['state','!=','cancel']]],
                ['Start with OK', [['name','ilike','OK']]]
            ],
           'filter_search_fields': ['name', 'code', 'ref']
       }">
    <list editable="bottom">
        <field name="name"/>
        <field name="state"/>
    </list>
</field>
```

### Available options

| Key                   | Type                      | Description                                                                |
| --------------------- | ------------------------- | -------------------------------------------------------------------------- |
| `filter_options`      | list of `[label, domain]` | Filter dropdown options. The options can apply to any field and any comparison. Optional. |
| `filter_search_fields` | list of field | Fields on which to enable free-text search. Optional.             |
| `enable_selection` | boolean | Enables row selection, allowing users to select multiple rows and perform bulk actions. `False` by default. |

**Important**: any field used in a domain (`filter_options` or
`filter_search_fields`) must be loaded in the `<list>` subview, whether visible
or not (`invisible="1"` if needed):

```xml
<field name="state" invisible="1"/>
```

### Supported features

* Filtering on any simple field (text, selection, number, date, boolean) using
  standard domain operators (`=`, `!=`, `like`, `ilike`, `in`, `<`, `>`, etc.)
* Combinations of conditions (`&`, `|`, `!`)

## Multiple Selection and Bulk Actions

Multiple selection can be enabled with `'enable_selection': true`. If multiple rows are
selected and the user clicks an action button, a confirmation popup offers to apply the action to all
selected rows instead of only the clicked row.

No additional view configuration is required: this works automatically when
the widget is used.

## Module Structure

```text
filter_selector/
├── static/src/
│   ├── components/
│   │   └── filter_toolbar.js(.xml)
│   │       → Filter dropdown + search UI
│   ├── fields/
│   │   ├── filter_selector_field.js(.xml)
│   │   │   → Main widget, assembles everything
│   │   ├── x2many_field_with_selectors.js
│   │   │   → Enables row checkboxes
│   └── hooks/
│       └── use_bulk_action_on_selection.js
│           → Applies an action button to the entire selection
```
