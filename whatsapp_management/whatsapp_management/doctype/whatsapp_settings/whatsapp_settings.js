// Copyright (c) 2024, Sowaan and contributors
// For license information, please see license.txt

frappe.ui.form.on("WhatsApp Settings", {
	refresh(frm) {

	},
    sync_conversations(frm){
        if(frm.doc.instance_id == undefined || frm.doc.token == undefined)
			frappe.throw("Instance Id or Token is missing. Please check fields")
		frappe.call({
			method: "whatsapp_management.whatsapp_management.apis.api.sync_conversations",
			callback: function(r) {
				console.log(r);
			},
			freeze: true,	
			freeze_message: __('Syncing conversations...')
		});
		
    },
	
    delete_conversations(frm){
		frappe.confirm(
			'Are you sure you want to delete the conversations?',
			function() {
				frappe.call({
					method: "whatsapp_management.whatsapp_management.apis.api.delete_conversations",
					callback: function(r) {
						console.log(r);
					},
					freeze: true,  
					freeze_message: __('Deleting conversations...')
				});
			},
			function() {
				frappe.msgprint(__('Deletion cancelled.'));
			}
		);
    }
});
