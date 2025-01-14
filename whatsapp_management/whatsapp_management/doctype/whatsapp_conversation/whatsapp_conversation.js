// Copyright (c) 2024, Sowaan and contributors
// For license information, please see license.txt

frappe.ui.form.on("WhatsApp Conversation", {
	refresh(frm) {
        frm.add_custom_button('Sync Messages', function () {
            if (!frm.doc.conversation_id) {
                frappe.throw(__('Conversation ID is missing. Please check the field.'));
            }
            frappe.call({
                method: "whatsapp_management.whatsapp_management.apis.api.sync_conver",
                args:{
                    conversation_id: frm.doc.conversation_id,
                    name: frm.doc.name
                },
                callback: function(r) {
                    console.log(r);
                },
                freeze: true,	
                freeze_message: __('Syncing messages...')
            });
        });
	},
});
