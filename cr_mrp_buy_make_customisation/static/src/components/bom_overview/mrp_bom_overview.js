/** @odoo-module **/

import { BomOverviewComponent } from "@mrp/components/bom_overview/mrp_bom_overview";
import { patch } from "@web/core/utils/patch";

patch(BomOverviewComponent.prototype, {
    setup() {
        super.setup();
        this.state.showOptions.buyMakeSelection = true;
    },
});