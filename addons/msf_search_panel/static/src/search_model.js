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

});