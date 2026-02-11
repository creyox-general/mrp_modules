/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { BomOverviewDisplayFilter } from "@mrp/components/bom_overview_display_filter/mrp_bom_overview_display_filter";

patch(BomOverviewDisplayFilter.prototype, {
    setup() {
        super.setup();
        this.displayOptions.approveToManufacture = _t('Approve to Manufacture');
        this.displayOptions.purchaseGroup = _t('Purchase Group');
        this.displayOptions.freeToUse = _t('Free to Use');
        this.displayOptions.displayCost = _t('Display Cost');
        this.displayOptions.customerRef = _t('Customer Ref');
        this.displayOptions.poLineId = _t('Related PO Line');
    },
});

patch(BomOverviewDisplayFilter, {
    props: {
        ...BomOverviewDisplayFilter.props,
        showOptions: {
            ...BomOverviewDisplayFilter.props.showOptions,
            approveToManufacture: Boolean,
            purchaseGroup: Boolean,
            freeToUse: Boolean,
            displayCost: Boolean,
            customerRef: Boolean,
            poLineId: Boolean,
        },
    },
});