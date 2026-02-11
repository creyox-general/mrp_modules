/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { BomOverviewComponent } from "@mrp/components/bom_overview/mrp_bom_overview";

patch(BomOverviewComponent.prototype, {
    setup() {
        super.setup();
        this.state.showOptions.approveToManufacture = true;
        this.state.showOptions.purchaseGroup = false;
        this.state.showOptions.freeToUse = true;
        this.state.showOptions.displayCost = false;
        this.state.showOptions.customerRef = true;
        this.state.showOptions.poLineId = true;
    }
});