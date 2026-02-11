/** @odoo-module **/

import { BomOverviewLine } from "@mrp/components/bom_overview_line/mrp_bom_overview_line";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";



patch(BomOverviewLine, {
    props: {
        ...BomOverviewLine.props,
        showOptions: {
            ...BomOverviewLine.props.showOptions,
            cfeQuantity: Boolean,
            moInternalRef: Boolean,
            lli: Boolean,
            approval1: Boolean,
            approval2: Boolean,
            defaultCode: Boolean,
            oldEverestPn: Boolean,
        },
    },
});


patch(BomOverviewLine.prototype, {

    setup() {
        super.setup();
        this.ormService = useService("orm");
        this.notification = useService("notification");
        this.cr_qty = this.data.quantity;
        this.canEditApproval2 = this.props.data.can_edit_approval_2 || false;
    },

//    async onCfeQuantityChange(event) {
//        const bomLineId = parseInt(event.target.getAttribute('data-bom-line-id'));
//        const newValue = event.target.value;
//        console.log('this.cr_qty : ',this.cr_qty)
//        if (bomLineId) {
//            await this.ormService.write("mrp.bom.line", [bomLineId], {
//                cfe_quantity: newValue
//            });
//            // Update data immediately
//            this.props.data.cfe_quantity = newValue;
//            this.props.data.has_cfe_quantity = !!newValue;
//        }
//    },

    async onCfeQuantityChange(event) {
        const bomLineId = parseInt(event.target.getAttribute('data-bom-line-id'));
        const newValue = parseFloat(event.target.value);
        const crQty = parseFloat(this.cr_qty || 0);
         console.log('newValue : ',newValue)
         console.log('crQty : ',crQty)

        // ✅ Validation: CFE must be SMALLER than CR
        if (newValue > crQty) {
                this.env.services.notification.add(
            "CFE Quantity must be smaller than Quantity.",
            { type: "danger" }
        );


            // Reset field to old value
            event.target.value = this.props.data.cfe_quantity || '';

            return;
        }

        if (bomLineId) {
            await this.ormService.write("mrp.bom.line", [bomLineId], {
                cfe_quantity: newValue
            });

            // Update UI instantly
            this.props.data.cfe_quantity = newValue;
            this.props.data.has_cfe_quantity = true;
        }
    },

    async onLliChange(event) {
        const bomLineId = parseInt(event.target.getAttribute('data-bom-line-id'));
        const isChecked = event.target.checked;
        await this._tryToggle(bomLineId, "lli", isChecked, event);
    },

    async onApproval1Change(event) {
        const bomLineId = parseInt(event.target.getAttribute('data-bom-line-id'));
        const isChecked = event.target.checked;
        await this._tryToggle(bomLineId, "approval_1", isChecked, event);
    },

    async onApproval2Change(event) {
    // Check permission first
    if (!this.canEditApproval2) {
        this.notification.add(
            "You don't have permission to edit Approval 2. Only Manufacturing/Admin or Purchase/Admin can edit this field.",
            { type: "warning" }
        );
        event.target.checked = !event.target.checked;
        event.preventDefault();
        return;
    }

    const bomLineId = parseInt(event.target.getAttribute('data-bom-line-id'));
    const isChecked = event.target.checked;
    await this._tryToggle(bomLineId, "approval_2", isChecked, event);
},

    _tryToggle: async function (bomLineId, field, newValue, event) {
    const rootBomId = this.props.data.root_bom_id;
    const productId = this.props.data.product_id;

    const lli = this.props.data.lli;
    const approval_1 = this.props.data.approval_1;
    const approval_2 = this.props.data.approval_2;

    await this.ormService.write("mrp.bom.line", [bomLineId], {
        [field]: newValue
    });
    this.props.data[field] = newValue;

    try {
        if (lli && approval_1 && approval_2) {
            const result = await this.ormService.call(
                "mrp.bom.line", "validate_third_boolean",
                [[bomLineId]],
                { context: { root_bom_id: rootBomId, qty: this.cr_qty } }
            );

            const results = Array.isArray(result) ? result : [result];


            for (const res of results) {
                // ✅ show all backend messages one by one
                if (res.messages && res.messages.length) {
                    for (const msg of res.messages) {
                        // decide type based on keywords in message
                        let type = "info";
                        if (msg.toLowerCase().includes("created")) {
                            type = "success";
                        } else if (msg.toLowerCase().includes("not created") || msg.toLowerCase().includes("no vendor")) {
                            type = "warning";
                        } else if (msg.toLowerCase().includes("error") || msg.toLowerCase().includes("failed")) {
                            type = "danger";
                        }
                        this.notification.add(msg, { type });
                    }
                } else {
                    // fallback if backend returns no messages
                    this.notification.add("No PO operation message received.", { type: "info" });
                }
            }



            }
        } catch (err) {
            const msg = (err && err.data && err.data.message) || (err && err.message) || "Validation failed";
            this.notification.add(msg, { type: "danger" });

            await this.ormService.write("mrp.bom.line", [bomLineId], {
                [field]: !newValue
            });
            this.props.data[field] = !newValue;
            if (event && event.target) {
                event.target.checked = !newValue;
            }
        }
},

async onProductManufacturerChange(event) {
    const bomLineId = parseInt(event.target.getAttribute("data-bom-line-id"));
    const selectedManufacturerId = parseInt(event.target.value);

    if (bomLineId && selectedManufacturerId) {
        try {
            // Directly write product_manufacturer_id on bom.line
            await this.ormService.write("mrp.bom.line", [bomLineId], {
                product_manufacturer_id: selectedManufacturerId,
            });

            // Optional: also call your helper method if you want extra logic
            await this.ormService.call(
                "mrp.bom.line",
                "set_product_manufacturer_id",
                [[bomLineId], selectedManufacturerId]
            );

        }catch (err) {
            const msg = (err?.data?.message) || (err?.message) || "Failed to save Vendor";
            this.notification.add(msg, { type: "danger" });
        }
    }
},

async goToAction(id, model) {
        if (model === "product.product" || model === "product.template") {
            const mainBomIds = await this.ormService.call(
                "mrp.bom",
                "search",
                [[
                    ["product_tmpl_id", "=", model === "product.template" ? id : false],
                ]],
            );

            if (mainBomIds && mainBomIds.length > 0) {
            return this.actionService.doAction({
                type: "ir.actions.act_window",
                res_model: "mrp.bom",
                res_id: mainBomIds[0],
                views: [[false, "form"]],
                target: "current",
                context: {
                    active_id: mainBomIds[0],
                },
            });
        }

        }

        return super.goToAction(id, model);
    },

openImageModal(productId, productName) {
    const safeProductName = productName || 'Product Image';
    const modalHtml = `
        <div class="modal fade" id="productImageModal" tabindex="-1" role="dialog">
            <div class="modal-dialog modal-lg modal-dialog-centered" role="document">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${safeProductName}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body text-center p-4">
                        <img src="/web/image/product.product/${productId}/image_1920"
                             class="img-fluid"
                             style="max-height: 70vh; max-width: 100%; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);"
                             alt="${safeProductName}"
                             onerror="this.src='/web/static/img/placeholder.png'"/>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary btn-sm close-modal-btn">Close</button>
                    </div>
                </div>
            </div>
        </div>
    `;

    const existingModal = document.getElementById('productImageModal');
    if (existingModal) {
        existingModal.remove();
    }

    const existingBackdrop = document.getElementById('productImageBackdrop');
    if (existingBackdrop) {
        existingBackdrop.remove();
    }

    document.body.insertAdjacentHTML('beforeend', modalHtml);

    const modalElement = document.getElementById('productImageModal');
    modalElement.classList.add('show');
    modalElement.style.display = 'block';
    document.body.classList.add('modal-open');

    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop fade show';
    backdrop.id = 'productImageBackdrop';
    document.body.appendChild(backdrop);

    const closeModal = () => {
        modalElement.classList.remove('show');
        modalElement.style.display = 'none';
        document.body.classList.remove('modal-open');
        backdrop.remove();
        modalElement.remove();
    };

    modalElement.querySelector('.btn-close').addEventListener('click', closeModal);
    modalElement.querySelector('.close-modal-btn').addEventListener('click', closeModal);
    backdrop.addEventListener('click', closeModal);
}
});

