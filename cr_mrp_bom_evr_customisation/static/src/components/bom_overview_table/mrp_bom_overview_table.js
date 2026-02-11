/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { BomOverviewTable } from "@mrp/components/bom_overview_table/mrp_bom_overview_table";

patch(BomOverviewTable.prototype, {
    get showApproveToManufacture() {
        return this.props.showOptions.approveToManufacture;
    },
    get showPurchaseGroup() {
        return this.props.showOptions.purchaseGroup;
    },
    get showFreeToUse() {
        return this.props.showOptions.freeToUse;
    },
    get showDisplayCost() {
        return this.props.showOptions.displayCost;
    },
    get showCustomerRef() {
        return this.props.showOptions.customerRef;
    },
    get showPoLineId() {
        return this.props.showOptions.poLineId;
    }
});

patch(BomOverviewTable, {
    props: {
        ...BomOverviewTable.props,
        showOptions: {
            ...BomOverviewTable.props.showOptions,
            approveToManufacture: Boolean,
            purchaseGroup: Boolean,
            freeToUse: Boolean,
            displayCost: Boolean,
            customerRef: Boolean,
            poLineId: Boolean,
        },
    },
});