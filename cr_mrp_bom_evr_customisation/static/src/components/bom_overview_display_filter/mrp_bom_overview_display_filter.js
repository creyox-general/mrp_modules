/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { BomOverviewDisplayFilter } from "@mrp/components/bom_overview_display_filter/mrp_bom_overview_display_filter";

patch(BomOverviewDisplayFilter.prototype, {
    setup() {
        super.setup();
        this.displayOptions.cfeQuantity = _t('CFE Quantity');
        this.displayOptions.moInternalRef = _t('MO ref');
        this.displayOptions.lli = _t('LLI');
        this.displayOptions.approval1 = _t('Approval 1');
        this.displayOptions.approval2 = _t('Approval 2');
        this.displayOptions.defaultCode = _t('Internal Reference');
        this.displayOptions.oldEverestPn = _t('Old Everest PN');
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
            cfeQuantity: Boolean,
            moInternalRef: Boolean,
            lli: Boolean,
            approval1: Boolean,
            approval2: Boolean,
            defaultCode: Boolean,
            oldEverestPn: Boolean,
            approveToManufacture: Boolean,
            purchaseGroup: Boolean,
            freeToUse: Boolean,
            displayCost: Boolean,
            customerRef: Boolean,
            poLineId: Boolean,
        },
    },
});