/** @odoo-module **/

import { registry } from "@web/core/registry";
import { x2ManyField } from "@web/views/fields/x2many/x2many_field";
import { X2ManyFieldWithSelectors } from "./x2many_field_with_selectors";
import { useBulkActionOnSelection } from "../hooks/use_bulk_action_on_selection";
import { Component, useRef, useState, onPatched, onMounted } from "@odoo/owl";
import { Domain } from "@web/core/domain";
import { FilterToolbar } from "../components/filter_toolbar";

export class FilterSelectorOne2Many extends Component {
    static template = "filter_selector.FilterSelectorOne2Many";
    static components = {
        X2ManyField: X2ManyFieldWithSelectors,
        FilterToolbar,
    };
    static props = { ...X2ManyFieldWithSelectors.props };

    setup() {
        this.rootRef = useRef("filterSelectorRoot");

        this.filterOptions = this.props.crudOptions?.filter_options || [];

        this.searchFields =
            this.props.crudOptions?.filter_search_fields ||
            (this.props.crudOptions?.filter_search_field
                ? [this.props.crudOptions.filter_search_field]
                : []);

        this.enableSelection =
            this.props.crudOptions?.enable_selection === true;

        this.state = useState({
            selected: 0,
            search: Object.fromEntries(
                this.searchFields.map((f) => [f, ""])
            ),
        });

        if (this.enableSelection) {
            useBulkActionOnSelection(() => this.list);
        }

        onMounted(() => this.applyFilters());
        onPatched(() => this.applyFilters());
    }

    get list() {
        return this.props.record.data[this.props.name];
    }

    onSelect(index) {
        this.state.selected = index;
        this.applyFilters();
    }

    onSearch(field, value) {
        this.state.search[field] = value;
        this.applyFilters();
    }

    applyFilters() {
        const root = this.rootRef.el;
        if (!root) return;

        const domains = [];

        if (this.filterOptions.length) {
            const [, domainArr] =
                this.filterOptions[this.state.selected];

            if (domainArr && domainArr.length) {
                domains.push(domainArr);
            }
        }

        for (const field of this.searchFields) {
            const value = this.state.search[field];

            if (value) {
                domains.push([[field, "ilike", value]]);
            }
        }

        const domain = domains.length
            ? Domain.and(domains)
            : new Domain([]);

        for (const record of this.list.records) {
            const matches = domain.contains(record.data);
            const row = root.querySelector(
                `tr[data-id="${record.id}"]`
            );

            if (row) {
                row.classList.toggle("d-none", !matches);
            }
        }
    }
}

export const filterSelectorOne2Many = {
    ...x2ManyField,
    component: FilterSelectorOne2Many,
    displayName: "One2many avec filtres rapides",
};

registry.category("fields").add(
    "filter_selector_one2many",
    filterSelectorOne2Many
);
