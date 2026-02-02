import { SearchModel } from "@web/search/search_model"
import { patch } from "@web/core/utils/patch";

patch(SearchModel.prototype, {
    /**
     * Returns which components are displayed in the current action. Components
     * are opt-out, meaning that they will be displayed as long as a falsy
     * value is not provided. With the search panel, the view type must also
     * match the given (or default) search panel view types if the search model
     * is instanciated in a view (this doesn't apply for any other action type).
     *
     * TeMPO : Overload this to display search panels in modal search windows as
     * as long there is one defined.
     * @private
     * @param {Object} [display={}]
     * @returns {{ controlPanel: Object | false, searchPanel: boolean, banner: boolean }}
     */
    _getDisplay(display = {}) {
        const { viewTypes } = this.searchPanelInfo;
        const { bannerRoute, viewType } = this.env.config;
        return {
            controlPanel: "controlPanel" in display ? display.controlPanel : {},
            searchPanel:
                this.sections.size &&
                (!viewType || viewTypes.includes(viewType)),
            banner: Boolean(bannerRoute),
        };
    },

    // /**
    //  * Updates the search domain and reloads sections if:
    //  * - the current search domain is different from the previous, or...
    //  * - a `shouldReload` flag has been set to true on the searchPanelInfo.
    //  * The latter means that the search domain has been modified while the
    //  * search panel was not displayed (and thus not reloaded) and the reload
    //  * should occur as soon as the search panel is visible again.
    //  * @private
    //  * @returns {Promise<void>}
    //  */
    // async _reloadSections() {
    //     this.blockNotification = true;
    //
    //     // Check whether the search domain changed
    //     const searchDomain = this._getDomain({ withSearchPanel: false });
    //     const searchDomainChanged =
    //         this.searchPanelInfo.shouldReload ||
    //         JSON.stringify(this.searchDomain) !== JSON.stringify(searchDomain);
    //     this.searchDomain = searchDomain;
    //     // CUSTOM TEMPO : Do not rebuild category every time, even if it has counters enabled
    //     // Previous check :
    //     // const toFetch = (section) =>
    //     //     section.enableCounters || (searchDomainChanged && !section.expand);
    //     const toFetch = (section) =>
    //         (searchDomainChanged && !section.expand);
    //     const categoriesToFetch = this.categories.filter(toFetch);
    //     const filtersToFetch = this.filters.filter(toFetch);
    //
    //     if (searchDomainChanged || Boolean(categoriesToFetch.length + filtersToFetch.length)) {
    //         if (this.display.searchPanel) {
    //             this.sectionsPromise = this._fetchSections(categoriesToFetch, filtersToFetch);
    //             if (this._shouldWaitForData(searchDomainChanged)) {
    //                 await this.sectionsPromise;
    //             }
    //         }
    //         // If no current search panel: will try to reload on next model update
    //         this.searchPanelInfo.shouldReload = !this.display.searchPanel;
    //     }
    //
    //     this.blockNotification = false;
    // }


    /**
     * Set the active value id of a given category.
     * @param {number} sectionId
     * @param {number} valueId
     */
    toggleCategoryValue(sectionId, valueId) {
        const category = this.sections.get(sectionId);
        category.activeValueId = valueId;
        this._notify();
    },

    /**
     * Fetches values for the given categories and filters.
     * @param {Category[]} categoriesToLoad
     * @param {Filter[]} filtersToLoad
     * @returns {Promise} resolved when all categories have been fetched
     */
    async _fetchSections(categoriesToLoad, filtersToLoad) {
        await this._fetchCategoriesCustom(categoriesToLoad);
        console.log("ALL CATEGORIES: ", this.categories);
        await this._fetchFilters(filtersToLoad);
        this.searchPanelInfo.loaded = true;
    },

    /**
     * Fetches values for each category at startup. At reload a category is
     * only fetched if needed.
     * @param {Category[]} categories
     * @returns {Promise} resolved when all categories have been fetched
     */
    async _fetchCategoriesCustom(categories) {

        // Overload only for hierarchized categories
        const treeCategories = [];
        const standardCategories = [];
        for (const category of categories) {
            // Check if category is hierarchized
            if (category.hierarchize) {
                const result = await this.orm.call(this.resModel, "search_panel_get_comodel_parent",
                    [category.fieldName])
                // Check if related field is a many2one with a defined parent
                if (!(result === false)) {
                    category.parentField = result;
                    treeCategories.push(category);
                    continue;
                }
            }
            // If category is not a hierarchized Many2one, we use standard behavior
            standardCategories.push(category);
        }

        const CategoryPromises = []
        // Non-hierarchized categories processing
        CategoryPromises.push(this._fetchCategories(standardCategories));

        // Hierarchized categories processing
        const filterDomain = this._getFilterDomain();
        const searchDomain = this.searchDomain;
        // Helper function to handle each tree category
        async function _fetchTreeCategory(searchModel, treeCategory) {
            const result = await searchModel.orm.call(searchModel.resModel, "search_panel_select_range_hierarchy",
                [treeCategory.fieldName], {
                    displayed_ids: treeCategory.displayedElements,
                    search_domain: searchDomain,
                    filter_domain: filterDomain,
                    category_domain: searchModel._getCategoryDomain(treeCategory.id),
                    parent_field: treeCategory.parentField,
                    context: searchModel.globalContext,
                    enable_counters: treeCategory.enableCounters,
                    expand: treeCategory.expand,
                    limit: treeCategory.limit,
                });
            // Unwrap values
            let { error_msg, values, rootIds } = result;
            console.log("Fetch Tree category: ", result);
            // Assign them to the category
            if (error_msg) {
                treeCategory.errorMsg = error_msg;
                values = [];
            }
            if (values.length > 0) {
                treeCategory.values = values;
            }
            treeCategory.rootIds = rootIds;
        }

        for (const treeCategory of treeCategories) {
            // Set default category values
            // Add displayedElements list property if newly created category
            if (!Object.hasOwn(treeCategory, "displayedElements")) {
                treeCategory.displayedElements = [];
            }
            // 0 is the value corresponding to the "All" default selection
            if (!Object.hasOwn(treeCategory, "activeValueId")) {
                treeCategory.activeValueId = 0;
            }
            // Update category values
            CategoryPromises.push(_fetchTreeCategory(this, treeCategory));
        }

        // Resolve calls for all categories
        await Promise.all(CategoryPromises);
    },

    /**
     * @param {string} sectionId
     * @param {Object} result
     */
    _createCategoryTree(sectionId, result) {
        const category = this.sections.get(sectionId);

        let { error_msg, parent_field: parentField, values } = result;
        if (error_msg) {
            category.errorMsg = error_msg;
            values = [];
        }
        console.log("Create categ tree: ", sectionId, result);
        if (category.hierarchize) {
            category.parentField = parentField;
        }
        let i = 1;
        for (const value of values) {
            category.values.set(
                value.id,
                Object.assign({}, value, {
                    childrenIds: [],
                    parentId: value[parentField] || false,
                })
            );
        }

        for (const value of values) {
            const { parentId } = category.values.get(value.id);
            if (parentId && category.values.has(parentId)) {
                category.values.get(parentId).childrenIds.push(value.id);
            }
        }
        // collect rootIds
        category.rootIds = [false];
        for (const value of values) {
            const { parentId } = category.values.get(value.id);
            if (!parentId) {
                category.rootIds.push(value.id);
            }
        }
        // Set active value from context
        const valueIds = [false, ...values.map((val) => val.id)];
        this._ensureCategoryValue(category, valueIds);
    }

});