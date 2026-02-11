/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { BomOverviewTable } from "@mrp/components/bom_overview_table/mrp_bom_overview_table";

patch(BomOverviewTable.prototype, {
    get showApproveToManufacture() {
        return this.props.showOptions.buyMakeSelection;
    },
});

patch(BomOverviewTable, {
    props: {
        ...BomOverviewTable.props,
        showOptions: {
            ...BomOverviewTable.props.showOptions,
            buyMakeSelection: Boolean,
        },
    },
});