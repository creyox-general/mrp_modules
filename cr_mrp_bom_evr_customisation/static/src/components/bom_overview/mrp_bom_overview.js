/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { BomOverviewComponent } from "@mrp/components/bom_overview/mrp_bom_overview";

patch(BomOverviewComponent.prototype, {
    setup() {
        super.setup();
        this.state.showOptions.cfeQuantity = true;
        this.state.showOptions.moInternalRef = true;
        this.state.showOptions.lli = true;
        this.state.showOptions.approval1 = true;
        this.state.showOptions.approval2 = true;
        this.state.showOptions.defaultCode = true;
        this.state.showOptions.oldEverestPn = true;
        this.state.showOptions.leadTimes = false;
        this.state.showOptions.availabilities = false;
        this.isEvr = false;
        this.state.showOptions.approveToManufacture = true;
        this.state.showOptions.purchaseGroup = false;
        this.state.showOptions.freeToUse = true;
        this.state.showOptions.displayCost = false;
        this.state.showOptions.customerRef = true;
        this.state.showOptions.poLineId = true;
    },
    async initBomData() {
        super.initBomData();
        const bomData = await this.getBomData();
        this.isEvr = bomData["is_evr"];
    },
     async getBomData() {
        const bomData = await super.getBomData();
        // Override to always set ecoAllowed to false
        this.state.showOptions.ecoAllowed = false;
        // Remove the eco_allowed flag from bomData if it exists
        if (bomData && 'is_eco_applied' in bomData) {
            bomData['is_eco_applied'] = false;
        }
        return bomData;
    },
});